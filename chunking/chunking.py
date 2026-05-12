# pyrefly: ignore [missing-import]
import argparse
import json
import re
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
MARKDOWN_ROOT   = Path("/run/media/bhat/workspace/projects/Kyoritsu RAG/data_markdown")
SQL_OUTPUT      = Path("/run/media/bhat/workspace/projects/Kyoritsu RAG/chunks.sql")

import os as _os

TARGET_TEXT_CHARS     = 800     # text sub-chunk target size
TARGET_TABLE_CHARS    = 3000    # table sub-chunk target size
TABLE_HEADER_LINES    = 4       # repeated at start of each table sub-chunk
TEXT_TO_TABLE_OVERLAP = 200     # tail of preceding text prepended to table

SUMMARY_BACKEND = _os.environ.get("SUMMARY_BACKEND", "ollama")  # "haiku" | "ollama" | "none"
OLLAMA_MODEL    = "qcwind/qwen2.5-7B-instruct-Q4_K_M"
OLLAMA_URL      = "http://localhost:11434/api/generate"

# ─── Org chart lookup (mirrors ingestion.py) ──────────────────────────────────
DEPT_SECTION_MAP: dict[int, dict[str, dict]] = {
    1: {  # 共立電機製作所
        "本社営業":           {"dept": "本社営業",           "dept_id": 11,  "section": None,               "section_id": None},
        "営業部":             {"dept": "本社営業",           "dept_id": 11,  "section": None,               "section_id": None},
        "東京支店":           {"dept": "本社営業",           "dept_id": 11,  "section": "東京支店",          "section_id": 911},
        "大阪支店":           {"dept": "本社営業",           "dept_id": 11,  "section": "大阪支店",          "section_id": 912},
        "福岡支店":           {"dept": "本社営業",           "dept_id": 11,  "section": "福岡支店",          "section_id": 913},
        "電気設計部":         {"dept": "設計部",             "dept_id": 12,  "section": "電気設計課",        "section_id": 121},
        "電気設計課":         {"dept": "設計部",             "dept_id": 12,  "section": "電気設計課",        "section_id": 121},
        "構造設計課":         {"dept": "設計部",             "dept_id": 12,  "section": "構造設計課",        "section_id": 122},
        "設計部":             {"dept": "設計部",             "dept_id": 12,  "section": None,               "section_id": None},
        "工程課":             {"dept": "生産管理部",         "dept_id": 13,  "section": "工程課",            "section_id": 131},
        "資材課":             {"dept": "生産管理部",         "dept_id": 13,  "section": "資材課",            "section_id": 132},
        "生産管理部":         {"dept": "生産管理部",         "dept_id": 13,  "section": None,               "section_id": None},
        "総務部":             {"dept": "総務部",             "dept_id": 14,  "section": None,               "section_id": None},
        "総務":               {"dept": "総務部",             "dept_id": 14,  "section": None,               "section_id": None},
        "AIIOT":              {"dept": "総務部",             "dept_id": 14,  "section": "KIP AI/IOTグループ","section_id": 141},
        "AI/IOT":             {"dept": "総務部",             "dept_id": 14,  "section": "KIP AI/IOTグループ","section_id": 141},
        "加工課":             {"dept": "製造部",             "dept_id": 15,  "section": "加工課",            "section_id": 151},
        "フレーム課":         {"dept": "製造部",             "dept_id": 15,  "section": "フレーム課",        "section_id": 152},
        "薄物1課":            {"dept": "製造部",             "dept_id": 15,  "section": "薄物1課",           "section_id": 153},
        "塗装課":             {"dept": "製造部",             "dept_id": 15,  "section": "塗装課",            "section_id": 154},
        "製造部":             {"dept": "製造部",             "dept_id": 15,  "section": None,               "section_id": None},
        "A-1課":              {"dept": "配線部",             "dept_id": 16,  "section": "A-1課",             "section_id": 161},
        "A-2課":              {"dept": "配線部",             "dept_id": 16,  "section": "A-2課",             "section_id": 162},
        "A-3課":              {"dept": "配線部",             "dept_id": 16,  "section": "A-3課",             "section_id": 163},
        "B-1課":              {"dept": "配線部",             "dept_id": 16,  "section": "B-1課",             "section_id": 164},
        "B-2課":              {"dept": "配線部",             "dept_id": 16,  "section": "B-2課",             "section_id": 165},
        "B-3課":              {"dept": "配線部",             "dept_id": 16,  "section": "B-3課",             "section_id": 166},
        "配線部":             {"dept": "配線部",             "dept_id": 16,  "section": None,               "section_id": None},
        "検査部":             {"dept": "検査部",             "dept_id": 17,  "section": None,               "section_id": None},
        "品質環境管理部":     {"dept": "品質環境管理部",     "dept_id": 18,  "section": None,               "section_id": None},
        "エンジニアリング部": {"dept": "エンジニアリング部", "dept_id": 19,  "section": None,               "section_id": None},
        "EG部":               {"dept": "エンジニアリング部", "dept_id": 19,  "section": None,               "section_id": None},
    },
    2: {  # 共立電照
        "企画開発課":         {"dept": "設計部",             "dept_id": 21,  "section": "企画開発課",        "section_id": 211},
        "製品開発課":         {"dept": "設計部",             "dept_id": 21,  "section": "製品開発課",        "section_id": 212},
        "設計課":             {"dept": "設計部",             "dept_id": 21,  "section": "設計課",            "section_id": 213},
        "設計部":             {"dept": "設計部",             "dept_id": 21,  "section": None,               "section_id": None},
        "資材課":             {"dept": "管理部",             "dept_id": 22,  "section": "資材課",            "section_id": 221},
        "管理部":             {"dept": "管理部",             "dept_id": 22,  "section": None,               "section_id": None},
        "工程管理課":         {"dept": "製造部",             "dept_id": 23,  "section": "工程管理課",        "section_id": 231},
        "薄物2課":            {"dept": "製造部",             "dept_id": 23,  "section": "薄物2課",           "section_id": 232},
        "配線組立課":         {"dept": "製造部",             "dept_id": 23,  "section": "配線組立課",        "section_id": 233},
        "組立課":             {"dept": "製造部",             "dept_id": 23,  "section": "配線組立課",        "section_id": 233},
        "検査課":             {"dept": "製造部",             "dept_id": 23,  "section": "検査課",            "section_id": 234},
        "製造部":             {"dept": "製造部",             "dept_id": 23,  "section": None,               "section_id": None},
        "営業全体":           {"dept": "営業部",             "dept_id": 24,  "section": "営業全体",          "section_id": 241},
        "宮崎沖縄":           {"dept": "営業部",             "dept_id": 24,  "section": "営業-宮崎・沖縄",   "section_id": 242},
        "宮崎・沖縄":         {"dept": "営業部",             "dept_id": 24,  "section": "営業-宮崎・沖縄",   "section_id": 242},
        "東京":               {"dept": "営業部",             "dept_id": 24,  "section": "営業-東京",         "section_id": 243},
        "大阪":               {"dept": "営業部",             "dept_id": 24,  "section": "営業-大阪",         "section_id": 244},
        "福岡":               {"dept": "営業部",             "dept_id": 24,  "section": "営業-福岡",         "section_id": 245},
        "営業部":             {"dept": "営業部",             "dept_id": 24,  "section": None,               "section_id": None},
        "品質環境管理課":     {"dept": "品質環境管理課",     "dept_id": 25,  "section": None,               "section_id": None},
        "808MERA":            {"dept": "808MERA",            "dept_id": 921, "section": None,               "section_id": None},
    },
}

_SKIP_PREFIXES = ("★", "スケジュール")

# ─── Metadata helpers ─────────────────────────────────────────────────────────

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


def make_doc_id(company_id: int, dept_id: int, section_id: int | None,
                year: int, month: int, is_action: bool) -> str:
    node   = section_id if section_id is not None else dept_id
    suffix = "002" if is_action else "001"
    return f"{company_id}-{node}-{year}-{month:02d}-{suffix}"


# ─── Text processing ──────────────────────────────────────────────────────────

_IMAGE_RE   = re.compile(r"!\[.*?\]\(.*?\)")
_HEADING_RE = re.compile(r"^(#{1,3})\s+.+$", re.MULTILINE)


def strip_images(text: str) -> str:
    return _IMAGE_RE.sub("", text)


def is_table_content(text: str) -> bool:
    return bool(re.search(r"^\|", text, re.MULTILINE))


def ends_with_table(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()]
    return bool(lines and lines[-1].strip().startswith("|"))


def split_by_headings(text: str) -> list[tuple[str, str]]:
    """Split on any #/##/### boundary.
    Returns list of (heading_line, body) pairs.
    Heading is '' for content before the first heading.
    """
    parts   = []
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [("", text.strip())]

    pre = text[: matches[0].start()].strip()
    if pre:
        parts.append(("", pre))

    for i, m in enumerate(matches):
        heading = m.group(0)
        start   = m.end()
        end     = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body    = text[start:end].strip()
        parts.append((heading, body))

    return parts


# ─── Summary generation ───────────────────────────────────────────────────────

_SUMMARY_PROMPT = (
    "以下は日本の企業の月次報告書の一部です。"
    "このチャンクに含まれるデータやトピックを1〜2文で簡潔に要約してください。\n\n{text}"
)


def generate_summary(text: str) -> str:
    if SUMMARY_BACKEND == "none":
        return ""
    prompt = _SUMMARY_PROMPT.format(text=text[:2000])
    resp = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    return json.loads(resp.content.decode("utf-8"))["response"].strip()


# ─── Chunk dataclass ──────────────────────────────────────────────────────────

@dataclass
class Chunk:
    doc_chunk_id: str
    doc_id:       str
    heading:      str
    chunk_text:   str
    chunk_type:   str        # "text" | "table"
    summary:      str
    company:      str
    dept:         str
    section:      str | None
    doc_type:     str
    year:         int
    month:        int


# ─── Sub-chunking ─────────────────────────────────────────────────────────────

def sub_chunk_text(body: str) -> list[str]:
    """Split text body at paragraph boundaries, accumulate up to TARGET_TEXT_CHARS."""
    if len(body) <= TARGET_TEXT_CHARS:
        return [body] if body.strip() else []

    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    chunks:  list[str] = []
    current: str       = ""

    for p in paragraphs:
        candidate = f"{current}\n\n{p}" if current else p
        if len(candidate) > TARGET_TEXT_CHARS and current:
            chunks.append(current)
            current = p
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def sub_chunk_table(body: str) -> list[str]:
    """Split table at row boundaries, repeat first 4 lines as header in each sub-chunk."""
    if len(body) <= TARGET_TABLE_CHARS:
        return [body] if body.strip() else []

    lines = body.splitlines()
    if len(lines) <= TABLE_HEADER_LINES:
        return [body]

    header = "\n".join(lines[:TABLE_HEADER_LINES])
    rows   = lines[TABLE_HEADER_LINES:]

    chunks:        list[str] = []
    current_rows:  list[str] = []
    current_size               = len(header)

    for row in rows:
        added = len(row) + 1
        if current_size + added > TARGET_TABLE_CHARS and current_rows:
            chunks.append(header + "\n" + "\n".join(current_rows))
            current_rows = [row]
            current_size = len(header) + added
        else:
            current_rows.append(row)
            current_size += added

    if current_rows:
        chunks.append(header + "\n" + "\n".join(current_rows))
    return chunks


# ─── Core chunking ────────────────────────────────────────────────────────────

def chunk_document(md_text: str, doc_meta: dict) -> list[Chunk]:
    """Chunk one markdown document. No overlap except text→table boundary (200 chars)."""
    text  = strip_images(md_text)
    parts = split_by_headings(text)

    chunks:         list[Chunk] = []
    last_text_tail: str         = ""   # 200-char tail of last emitted text sub-chunk
    idx                          = 0
    seen_texts:     set[str]    = set()  # dedup: skip if identical chunk_text already emitted

    def emit(heading: str, sub: str, chunk_type: str, prepend: str = "") -> None:
        nonlocal idx
        pieces = []
        if heading:
            pieces.append(heading)
        if prepend:
            pieces.append(prepend)
        pieces.append(sub)
        chunk_text = "\n".join(pieces).strip()

        if not chunk_text or chunk_text in seen_texts:
            return
        seen_texts.add(chunk_text)

        try:
            summary = generate_summary(chunk_text)
        except Exception as exc:
            log.warning("Summary failed %s chunk-%d: %s", doc_meta["doc_id"], idx, exc)
            summary = heading or chunk_text[:100]

        chunks.append(Chunk(
            doc_chunk_id = f"{doc_meta['doc_id']}-chunk-{idx}",
            doc_id       = doc_meta["doc_id"],
            heading      = heading,
            chunk_text   = chunk_text,
            chunk_type   = chunk_type,
            summary      = summary,
            company      = doc_meta["company"],
            dept         = doc_meta["dept"],
            section      = doc_meta["section"],
            doc_type     = doc_meta["doc_type"],
            year         = doc_meta["year"],
            month        = doc_meta["month"],
        ))
        idx += 1

    for heading, body in parts:
        if not body:
            continue

        chunk_type = "table" if is_table_content(body) else "text"

        if chunk_type == "text":
            for sub in sub_chunk_text(body):
                emit(heading, sub, "text")
                last_text_tail = sub[-TEXT_TO_TABLE_OVERLAP:]
        else:
            sub_chunks = sub_chunk_table(body)
            for i, sub in enumerate(sub_chunks):
                prepend = last_text_tail if i == 0 else ""
                emit(heading, sub, "table", prepend=prepend)
            last_text_tail = ""

    return chunks


# ─── SQL output ───────────────────────────────────────────────────────────────

def _q(val) -> str:
    if val is None:
        return "NULL"
    return "'" + str(val).replace("'", "''") + "'"


def make_chunk_sql(c: Chunk) -> str:
    return (
        "INSERT INTO document_chunks "
        "(doc_chunk_id, doc_id, chunk, chunk_type, summary, "
        "company, dept, section, doc_type, year, month) VALUES ("
        f"{_q(c.doc_chunk_id)}, {_q(c.doc_id)}, {_q(c.chunk_text)}, "
        f"{_q(c.chunk_type)}, {_q(c.summary)}, "
        f"{_q(c.company)}, {_q(c.dept)}, {_q(c.section)}, "
        f"{_q(c.doc_type)}, {c.year}, {c.month});"
    )


# ─── File processor ───────────────────────────────────────────────────────────

def process_file(md_path: Path) -> list[Chunk] | None:
    """Derive metadata from path, chunk document. Returns None if unmapped."""
    parts = md_path.relative_to(MARKDOWN_ROOT).parts
    if len(parts) < 4:
        log.warning("Unexpected path depth: %s", md_path)
        return None

    _, month_folder, company_folder, *_ = parts

    ym = extract_year_month(month_folder)
    if ym is None:
        return None
    year, month = ym

    company = detect_company(company_folder)
    if company is None:
        return None
    company_id, company_name = company

    name = extract_name(md_path.name)
    org  = lookup_org(name, company_id)
    if org is None:
        log.warning("UNMAPPED %s (name=%r)", md_path.name, name)
        return None

    is_action = is_action_folder(company_folder)
    doc_id    = make_doc_id(company_id, org["dept_id"], org["section_id"], year, month, is_action)

    doc_meta = {
        "doc_id":   doc_id,
        "company":  company_name,
        "dept":     org["dept"],
        "section":  org["section"],
        "doc_type": "action_plan" if is_action else "monthly_report",
        "year":     year,
        "month":    month,
    }

    try:
        return chunk_document(md_path.read_text(encoding="utf-8"), doc_meta)
    except Exception as exc:
        log.error("FAILED %s: %s", md_path, exc)
        return None


# ─── Main pipeline ────────────────────────────────────────────────────────────

def collect_md_files_ordered() -> list[Path]:
    """Deterministic order: year → month → company → filename."""
    files: list[Path] = []
    for year_dir in sorted(MARKDOWN_ROOT.iterdir()):
        if not year_dir.is_dir() or not re.fullmatch(r"\d{4}", year_dir.name):
            continue

        month_dirs = []
        for d in year_dir.iterdir():
            if not d.is_dir():
                continue
            ym = extract_year_month(d.name)
            if ym:
                month_dirs.append((ym, d))
        month_dirs.sort(key=lambda x: x[0])

        for _, month_dir in month_dirs:
            for company_dir in sorted(month_dir.iterdir()):
                if not company_dir.is_dir():
                    continue
                for md_file in sorted(company_dir.iterdir()):
                    if not md_file.is_file() or md_file.suffix != ".md":
                        continue
                    if md_file.name.startswith(_SKIP_PREFIXES):
                        continue
                    files.append(md_file)
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Chunk only first N successfully mapped files")
    args = parser.parse_args()

    stats = {"files": 0, "chunks": 0, "unmapped": 0, "errors": 0}
    all_files = collect_md_files_ordered()
    log.info("Found %d markdown files; limit=%s", len(all_files), args.limit)

    with SQL_OUTPUT.open("w", encoding="utf-8") as sql_fh:
        sql_fh.write("-- Kyoritsu RAG — document_chunks inserts\n\n")

        for md_file in all_files:
            if args.limit is not None and stats["files"] >= args.limit:
                break

            chunks = process_file(md_file)
            if chunks is None:
                stats["unmapped"] += 1
                continue

            for chunk in chunks:
                sql_fh.write(make_chunk_sql(chunk) + "\n")

            stats["files"]  += 1
            stats["chunks"] += len(chunks)
            log.info("OK  %-50s → %d chunks", md_file.name, len(chunks))

    log.info(
        "Done.  Files=%d  Chunks=%d  Unmapped=%d  Errors=%d",
        stats["files"], stats["chunks"], stats["unmapped"], stats["errors"],
    )


if __name__ == "__main__":
    main()
