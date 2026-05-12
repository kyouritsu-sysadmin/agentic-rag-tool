# pyrefly: ignore [missing-import]
"""
embedding.py — Generate and store ruri-v3-310m embeddings for all chunks.

Reads document_chunks from PostgreSQL, encodes with prefix "検索文書: ",
and batch-UPDATEs the embedding column.

Resume-safe: skips rows where embedding IS NOT NULL.

Usage:
    python embedding.py               # embed all pending chunks
    python embedding.py --batch 32    # smaller GPU batch (lower VRAM)
    python embedding.py --limit 500   # embed only N chunks (smoke test)
"""
import argparse
import logging
import time
from typing import Generator
import psycopg2
# pyrefly: ignore [missing-import]
import torch
import torch.nn.functional as F  # pyrefly: ignore
from transformers import AutoTokenizer, AutoModel  # pyrefly: ignore
from tqdm import tqdm  # pyrefly: ignore

# ─── Config ───────────────────────────────────────────────────────────────────
MODEL_NAME   = "cl-nagoya/ruri-v3-310m"
PREFIX       = "検索文書: "
EMBED_DIM    = 768

DB_HOST      = "localhost"
DB_PORT      = 5434
DB_NAME      = "rag_database"
DB_USER      = "admin"
DB_PASSWORD  = "admin1234"

GPU_BATCH    = 8     # reduced: table chunks avg 962 tokens, need headroom for 8192 max
DB_BATCH     = 512   # rows fetched / updated per DB roundtrip

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def fetch_pending(conn, limit: int | None) -> Generator[tuple[str, str], None, None]:
    """Yield (doc_chunk_id, chunk_text) for all rows with embedding IS NULL."""
    sql = """
        SELECT doc_chunk_id, chunk
        FROM document_chunks
        WHERE embedding IS NULL
        ORDER BY doc_chunk_id
    """
    if limit:
        sql += f" LIMIT {limit}"

    with conn.cursor(name="pending_chunks") as cur:   # server-side cursor
        cur.itersize = DB_BATCH
        cur.execute(sql)
        for row in cur:
            yield row


def bulk_update(conn, rows: list[tuple[str, list[float]]]) -> None:
    """UPDATE embedding for a batch of (doc_chunk_id, vector) pairs."""
    sql = """
        UPDATE document_chunks
        SET embedding = %s::vector
        WHERE doc_chunk_id = %s
    """
    with conn.cursor() as cur:
        cur.executemany(sql, [
            ("[" + ",".join(f"{v:.8f}" for v in vec) + "]", cid)
            for cid, vec in rows
        ])
    conn.commit()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=GPU_BATCH,
                        help="GPU batch size (default 64)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max chunks to embed (smoke test)")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    log.info("Loading model %s ...", MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model     = AutoModel.from_pretrained(MODEL_NAME).to(device).eval()
    log.info("Model loaded — hidden size: %d", model.config.hidden_size)
    if model.config.hidden_size != EMBED_DIM:
        raise ValueError(
            f"Model output dim {model.config.hidden_size} != DB column vector({EMBED_DIM}). "
            "Update EMBED_DIM or the schema before running."
        )
    log.info("Model max position embeddings: %d", model.config.max_position_embeddings)

    read_conn  = get_conn()   # server-side cursor for streaming rows
    write_conn = get_conn()   # separate connection for UPDATE + commit

    # count pending
    with read_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL")
        total = cur.fetchone()[0]

    if args.limit:
        total = min(total, args.limit)

    log.info("Pending chunks: %d", total)
    if total == 0:
        log.info("Nothing to embed — all chunks already have embeddings.")
        read_conn.close(); write_conn.close()
        return

    t_start   = time.time()
    processed = 0
    buffer: list[tuple[str, str]] = []   # (chunk_id, text) accumulator

    truncated_total = 0

    def encode_batch(texts: list[str]) -> list[list[float]]:
        nonlocal truncated_total
        encoded = tokenizer(texts, padding=True, truncation=True,
                            max_length=8192, return_tensors="pt").to(device)
        # warn if any sequence was actually truncated
        n_truncated = (encoded["attention_mask"].sum(dim=1) == 8192).sum().item()
        if n_truncated:
            truncated_total += n_truncated
            log.warning("%d chunk(s) in this batch hit max_length=8192 and were truncated", n_truncated)
        with torch.no_grad():
            out = model(**encoded)
        mask   = encoded["attention_mask"].unsqueeze(-1).float()
        pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        normed = F.normalize(pooled, p=2, dim=1)
        return normed.cpu().tolist()

    def flush(buf: list[tuple[str, str]]) -> None:
        nonlocal processed
        ids   = [r[0] for r in buf]
        texts = [PREFIX + r[1] for r in buf]

        vecs: list[list[float]] = []
        for i in range(0, len(texts), args.batch):
            vecs.extend(encode_batch(texts[i : i + args.batch]))

        bulk_update(write_conn, list(zip(ids, vecs)))
        processed += len(buf)

    with tqdm(total=total, unit="chunk", dynamic_ncols=True) as bar:
        for chunk_id, chunk_text in fetch_pending(read_conn, args.limit):
            buffer.append((chunk_id, chunk_text))

            if len(buffer) >= DB_BATCH:
                flush(buffer)
                bar.update(len(buffer))
                buffer.clear()

        if buffer:
            flush(buffer)
            bar.update(len(buffer))
            buffer.clear()

    elapsed = time.time() - t_start
    log.info("Done. %d chunks embedded in %.1f min (%.1f chunks/sec)",
             processed, elapsed / 60, processed / elapsed)
    if truncated_total:
        log.warning("TRUNCATION SUMMARY: %d chunks exceeded max_length=8192 and lost tail content",
                    truncated_total)

    # final verification
    with write_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
        filled = cur.fetchone()[0]
    log.info("Embeddings in DB: %d / %d", filled, filled + (total - processed))

    read_conn.close()
    write_conn.close()


if __name__ == "__main__":
    main()
