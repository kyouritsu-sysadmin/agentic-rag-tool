# pyrefly: ignore [missing-import]
import re
import time
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import torch
    _HAS_CUDA = torch.cuda.is_available()
except ImportError:
    _HAS_CUDA = False

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

from config.org import ORG_CHART as DEPT_SECTION_MAP

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

DATA_ROOT     = Path("/run/media/bhat/workspace/projects/Kyoritsu RAG/data")
MARKDOWN_ROOT = Path("/run/media/bhat/workspace/projects/Kyoritsu RAG/data_markdown")
SQL_OUTPUT    = Path("/run/media/bhat/workspace/projects/Kyoritsu RAG/documents.sql")

BATCH_SIZE     = 20 # files converted before checking GPU temp
TEMP_THRESHOLD = 75  # °C — wait until GPU cools below this
TEMP_POLL_SEC  = 30  # seconds between temp checks during cooldown


def gpu_temp() -> int:
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            text=True,
        )
        return int(out.strip().split("\n")[0])
    except Exception:
        return 0


def cooldown_if_needed(batch_num: int) -> None:
    if _HAS_CUDA:
        torch.cuda.empty_cache()
    temp = gpu_temp()
    if temp <= TEMP_THRESHOLD:
        return
    log.info("--- batch %d done, GPU at %d°C — waiting to cool below %d°C ---",
             batch_num, temp, TEMP_THRESHOLD)
    while True:
        time.sleep(TEMP_POLL_SEC)
        temp = gpu_temp()
        log.info("    GPU temp: %d°C", temp)
        if temp <= TEMP_THRESHOLD:
            log.info("    GPU cooled to %d°C, resuming.", temp)
            break

_SKIP_PREFIXES = ("★", "スケジュール")
_NON_PDF_EXTS  = {".mp4", ".db", ".xlsx", ".xls", ".mp3", ".zip"}


def detect_company(folder_name: str) -> tuple[int, str] | None:
    if re.search(r"電照", folder_name):
        return (2, "共立電照")
    if re.search(r"電機", folder_name):
        return (1, "共立電機製作所")
    return None


def extract_year_month(folder_name: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{4})年(\d{1,2})月度", folder_name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def extract_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d+-\s*", "", stem)
    stem = re.sub(r"\s*\d+月.*$", "", stem)
    stem = re.sub(r"[「【（(].*$", "", stem)
    return stem.strip()


def lookup_org(name: str, company_id: int) -> dict | None:
    table = DEPT_SECTION_MAP.get(company_id, {})
    if name in table:
        return table[name]
    for key, val in table.items():
        if key in name or name in key:
            return val
    return None


def is_action_folder(folder_name: str) -> bool:
    return bool(re.search(r"アクション", folder_name))


def should_skip(filename: str) -> bool:
    p = Path(filename)
    if p.suffix.lower() in _NON_PDF_EXTS or p.suffix.lower() != ".pdf":
        return True
    return p.name.startswith(_SKIP_PREFIXES)


def make_doc_id(company_id: int, dept_id: int, section_id: int | None,
                year: int, month: int, is_action: bool) -> str:
    node   = section_id if section_id is not None else dept_id
    suffix = "002" if is_action else "001"
    return f"{company_id}-{node}-{year}-{month:02d}-{suffix}"


def _q(val) -> str:
    if val is None:
        return "NULL"
    return "'" + str(val).replace("'", "''") + "'"


def make_sql(doc: dict) -> str:
    return (
        "INSERT INTO Documents "
        "(DocumentId, company, Dept, Section, doc_type, Year, month, path, created_at) VALUES ("
        f"{_q(doc['document_id'])}, {_q(doc['company'])}, {_q(doc['dept'])}, "
        f"{_q(doc['section'])}, {_q(doc['doc_type'])}, "
        f"{doc['year']}, {doc['month']}, "
        f"{_q(doc['path'])}, {_q(doc['created_at'])});"
    )


def process_file(
    pdf_path: Path,
    year: int, month: int,
    company_id: int, company_name: str,
    is_action: bool,
    converter: PdfConverter,
    sql_fh,
) -> str:
    if should_skip(pdf_path.name):
        log.info("SKIP     %s", pdf_path.name)
        return "skipped"

    name = extract_name(pdf_path.name)
    org  = lookup_org(name, company_id)

    if org is None:
        log.warning("UNMAPPED %s  (parsed name=%r)", pdf_path, name)
        return "unmapped"

    doc_id     = make_doc_id(company_id, org["dept_id"], org["section_id"], year, month, is_action)
    doc_type   = "action_plan" if is_action else "monthly_report"
    created_at = f"{year}-{month:02d}-01"
    md_path    = MARKDOWN_ROOT / pdf_path.relative_to(DATA_ROOT).with_suffix(".md")

    log.info("CONVERT  %s  →  %s", pdf_path.name, doc_id)
    try:
        rendered       = converter(filepath=str(pdf_path))
        md_text, _, _  = text_from_rendered(rendered)
    except Exception as exc:
        log.error("FAILED   %s  %s", pdf_path, exc)
        return "failed"

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_text, encoding="utf-8")

    sql_fh.write(make_sql({
        "document_id": doc_id,
        "company":     company_name,
        "dept":        org["dept"],
        "section":     org["section"],
        "doc_type":    doc_type,
        "year":        year,
        "month":       month,
        "path":        str(md_path),
        "created_at":  created_at,
    }) + "\n")

    log.info("OK       %s", doc_id)
    return "ok"


def main() -> None:
    MARKDOWN_ROOT.mkdir(parents=True, exist_ok=True)

    config = {
    "recognition_batch_size": 128,  # marker default is 48 — way too low
    "layout_batch_size": 64,
    "detection_batch_size": 64,
    "table_rec_batch_size": 64,
    "ocr_error_batch_size": 64,
    }

    log.info("Loading marker models...")
    converter = PdfConverter(artifact_dict=create_model_dict(),config= config)
    log.info("Models ready. Starting ingestion from: %s", DATA_ROOT)

    stats: dict[str, int] = {"ok": 0, "skipped": 0, "unmapped": 0, "failed": 0}
    batch_count = 0

    with SQL_OUTPUT.open("w", encoding="utf-8") as sql_fh:
        sql_fh.write("-- Kyoritsu RAG — Documents inserts\n\n")

        for year_dir in sorted(DATA_ROOT.iterdir()):
            if not year_dir.is_dir() or not re.fullmatch(r"\d{4}", year_dir.name):
                continue

            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir():
                    continue
                ym = extract_year_month(month_dir.name)
                if ym is None:
                    log.warning("Cannot parse year/month: %s", month_dir.name)
                    continue
                year, month = ym

                for company_dir in sorted(month_dir.iterdir()):
                    if not company_dir.is_dir():
                        continue
                    company = detect_company(company_dir.name)
                    if company is None:
                        log.warning("Cannot detect company: %s", company_dir.name)
                        continue
                    company_id, company_name = company
                    is_action = is_action_folder(company_dir.name)

                    for pdf_file in sorted(company_dir.iterdir()):
                        if not pdf_file.is_file():
                            continue
                        result = process_file(
                            pdf_file, year, month,
                            company_id, company_name,
                            is_action, converter, sql_fh,
                        )
                        stats[result] = stats.get(result, 0) + 1

                        if result in ("ok", "failed"):
                            batch_count += 1
                            if batch_count % BATCH_SIZE == 0:
                                cooldown_if_needed(batch_count // BATCH_SIZE)

    log.info(
        "Done.  OK=%d  Skipped=%d  Unmapped=%d  Failed=%d",
        stats["ok"], stats["skipped"], stats["unmapped"], stats["failed"],
    )


if __name__ == "__main__":
    main()
