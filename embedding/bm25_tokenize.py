# pyrefly: ignore [missing-import]
"""
bm25_tokenize.py — Sudachi tokenization → PostgreSQL tsvector for BM25 search.

Reads document_chunks where tsv IS NULL, tokenizes each chunk with Sudachi
(mode B), then batch-UPDATEs tsv = to_tsvector('simple', tokenized_text).

Mode B (middle segmentation) is used because:
  - Mode A over-segments compound nouns (製作 + 所 instead of 製作所)
  - Mode C under-segments, producing phrases rather than searchable units
  - Mode B keeps domain terms intact while still splitting for retrieval

Resume-safe: only processes rows where tsv IS NULL.

Usage:
    python bm25_tokenize.py               # tokenize all pending chunks
    python bm25_tokenize.py --limit 500   # smoke test
    python bm25_tokenize.py --batch 256   # adjust DB batch size
"""
import argparse
import logging
import time
from typing import Generator

import psycopg2
# pyrefly: ignore [missing-import]
from sudachipy import dictionary, tokenizer
from tqdm import tqdm

# ─── Config ───────────────────────────────────────────────────────────────────
DB_HOST     = "localhost"
DB_PORT     = 5434
DB_NAME     = "rag_database"
DB_USER     = "admin"
DB_PASSWORD = "admin1234"

DB_BATCH    = 512
SPLIT_MODE  = tokenizer.Tokenizer.SplitMode.B

# Part-of-speech tags to drop (particles, auxiliary verbs, punctuation)
_DROP_POS = {"助詞", "助動詞", "補助記号", "空白"}

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ─── Sudachi setup ────────────────────────────────────────────────────────────

def build_tokenizer():
    return dictionary.Dictionary().create()


_SUDACHI_MAX_BYTES = 48000  # hard limit is 49149; leave headroom

_sudachi_truncation_count = 0

def tokenize(tok, text: str) -> str:
    """Return space-separated content words for to_tsvector('simple', ...)."""
    global _sudachi_truncation_count
    encoded = text.encode("utf-8")
    if len(encoded) > _SUDACHI_MAX_BYTES:
        _sudachi_truncation_count += 1
        log.warning(
            "Chunk truncated for Sudachi: %d bytes → %d bytes (occurrence #%d). "
            "BM25 index covers only first %.0f%% of this chunk.",
            len(encoded), _SUDACHI_MAX_BYTES, _sudachi_truncation_count,
            _SUDACHI_MAX_BYTES / len(encoded) * 100,
        )
        text = encoded[:_SUDACHI_MAX_BYTES].decode("utf-8", errors="ignore")

    morphemes = tok.tokenize(text, SPLIT_MODE)
    tokens = []
    for m in morphemes:
        pos = m.part_of_speech()[0]   # main POS category
        if pos in _DROP_POS:
            continue
        surface = m.surface().strip()
        if surface:
            tokens.append(surface)
    return " ".join(tokens)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def fetch_pending(conn, limit: int | None) -> Generator[tuple[str, str], None, None]:
    sql = """
        SELECT doc_chunk_id, chunk
        FROM document_chunks
        WHERE tsv IS NULL
        ORDER BY doc_chunk_id
    """
    if limit:
        sql += f" LIMIT {limit}"
    with conn.cursor(name="pending_tsv") as cur:
        cur.itersize = DB_BATCH
        cur.execute(sql)
        for row in cur:
            yield row


def bulk_update(conn, rows: list[tuple[str, str]]) -> None:
    """UPDATE tsv = to_tsvector('simple', tokenized) for a batch."""
    sql = """
        UPDATE document_chunks
        SET tsv = to_tsvector('simple', %s)
        WHERE doc_chunk_id = %s
    """
    with conn.cursor() as cur:
        cur.executemany(sql, [(tok_text, cid) for cid, tok_text in rows])
    conn.commit()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Max chunks to tokenize (smoke test)")
    parser.add_argument("--batch", type=int, default=DB_BATCH,
                        help="DB batch size (default 512)")
    args = parser.parse_args()

    log.info("Initializing Sudachi (mode B) ...")
    tok = build_tokenizer()
    log.info("Sudachi ready.")

    read_conn  = get_conn()   # server-side cursor for streaming rows
    write_conn = get_conn()   # separate connection for UPDATE + commit

    with read_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_chunks WHERE tsv IS NULL")
        total = cur.fetchone()[0]

    if args.limit:
        total = min(total, args.limit)

    log.info("Pending chunks: %d", total)
    if total == 0:
        log.info("Nothing to tokenize — all chunks already have tsv.")
        read_conn.close(); write_conn.close()
        return

    t_start   = time.time()
    processed = 0
    buffer: list[tuple[str, str]] = []  # (chunk_id, tokenized_text)

    def flush(buf: list[tuple[str, str]]) -> None:
        nonlocal processed
        tokenized = [(cid, tokenize(tok, text)) for cid, text in buf]
        bulk_update(write_conn, tokenized)
        processed += len(buf)

    with tqdm(total=total, unit="chunk", dynamic_ncols=True) as bar:
        for chunk_id, chunk_text in fetch_pending(read_conn, args.limit):
            buffer.append((chunk_id, chunk_text))

            if len(buffer) >= args.batch:
                flush(buffer)
                bar.update(len(buffer))
                buffer.clear()

        if buffer:
            flush(buffer)
            bar.update(len(buffer))
            buffer.clear()

    elapsed = time.time() - t_start
    log.info("Done. %d chunks tokenized in %.1f min (%.1f chunks/sec)",
             processed, elapsed / 60, processed / elapsed)

    with write_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_chunks WHERE tsv IS NOT NULL")
        filled = cur.fetchone()[0]
    log.info("tsv filled: %d / %d", filled, filled + (total - processed))

    read_conn.close()
    write_conn.close()


if __name__ == "__main__":
    main()
