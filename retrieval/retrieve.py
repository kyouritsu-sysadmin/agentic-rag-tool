# pyrefly: ignore [missing-import]
"""
retrieve.py — Hybrid retrieval: BM25 + vector → RRF → bge-reranker-v2-m3.

Pipeline:
  1. Parse temporal cues (year/month) from the query string
  2. Embed query with prefix "検索クエリ: " via ruri-v3-310m
  3. BM25 search (Sudachi tokenize → ts_rank) — top BM25_K candidates
  4. Vector search (pgvector cosine) — top VEC_K candidates
  5. RRF fusion → top RRF_K candidates passed to reranker
  6. bge-reranker-v2-m3 cross-encoder → return top FINAL_K

Usage:
    python retrieve.py "共立電機製作所の2024年品質報告の主要課題は？"
    python retrieve.py --year 2024 --company "共立電機製作所" "品質報告の課題"
    python retrieve.py --top-k 5 --no-rerank "検索クエリ"
"""
import argparse
import dataclasses
import logging
import re
import sys
from pathlib import Path
from typing import Optional

import psycopg2
# pyrefly: ignore [missing-import]
import torch
# pyrefly: ignore [missing-import]
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification  # pyrefly: ignore
from sudachipy import dictionary, tokenizer as sudachi_tokenizer  # pyrefly: ignore

# ─── Config ───────────────────────────────────────────────────────────────────
EMBED_MODEL   = "cl-nagoya/ruri-v3-310m"
RERANK_MODEL  = "BAAI/bge-reranker-v2-m3"
QUERY_PREFIX  = "検索クエリ: "
EMBED_DIM     = 768

DB_HOST       = "localhost"
DB_PORT       = 5434
DB_NAME       = "rag_database"
DB_USER       = "admin"
DB_PASSWORD   = "admin1234"

BM25_K  = 50   # BM25 candidates
VEC_K   = 50   # vector candidates
RRF_K   = 20   # candidates sent to reranker after RRF fusion
RRF_C   = 60   # RRF constant (standard value)
FINAL_K = 8    # final results returned

SPLIT_MODE = sudachi_tokenizer.Tokenizer.SplitMode.B
_DROP_POS  = {"助詞", "助動詞", "補助記号", "空白"}

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ─── Result type ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class RetrievedChunk:
    doc_chunk_id: str
    doc_id:       str
    chunk:        str
    chunk_type:   str
    company:      str
    dept:         str
    section:      Optional[str]
    doc_type:     str
    year:         int
    month:        int
    meeting_date: Optional[str]
    bm25_rank:    Optional[int]
    vec_rank:     Optional[int]
    rrf_score:    float
    rerank_score: Optional[float]


# ─── Temporal parser ──────────────────────────────────────────────────────────

_YEAR_RE  = re.compile(r"(\d{4})年")
_MONTH_RE = re.compile(r"(\d{1,2})月")

def parse_temporal(query: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (year, month) from Japanese date mentions in query. Returns None if absent."""
    year  = int(m.group(1)) if (m := _YEAR_RE.search(query)) else None
    month = int(m.group(1)) if (m := _MONTH_RE.search(query)) else None
    return year, month


# ─── Sudachi tokenizer ────────────────────────────────────────────────────────

def build_sudachi():
    return dictionary.Dictionary().create()

def tokenize_query(tok, text: str) -> list[str]:
    """Tokenize query with Sudachi, drop stopword POS. Returns list of token strings."""
    morphemes = tok.tokenize(text, SPLIT_MODE)
    return [
        m.surface().strip()
        for m in morphemes
        if m.part_of_speech()[0] not in _DROP_POS and m.surface().strip()
    ]

def build_tsquery(tokens: list[str]) -> str:
    """Build a simple OR tsquery string from token list."""
    if not tokens:
        return ""
    # escape any special tsquery chars in individual tokens
    safe = [re.sub(r"[&|!():*']", "", t) for t in tokens]
    safe = [t for t in safe if t]
    return " | ".join(safe)


# ─── Embedding ────────────────────────────────────────────────────────────────

def load_embed_model(device: str):
    log.info("Loading embedding model %s ...", EMBED_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(EMBED_MODEL)
    model     = AutoModel.from_pretrained(EMBED_MODEL).to(device).eval()
    assert model.config.hidden_size == EMBED_DIM, (
        f"Embedding dim mismatch: {model.config.hidden_size} != {EMBED_DIM}"
    )
    return tokenizer, model

def embed_query(tokenizer, model, query: str, device: str) -> list[float]:
    text    = QUERY_PREFIX + query
    encoded = tokenizer([text], padding=True, truncation=True,
                        max_length=8192, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**encoded)
    mask   = encoded["attention_mask"].unsqueeze(-1).float()
    pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
    normed = F.normalize(pooled, p=2, dim=1)
    return normed[0].cpu().tolist()


# ─── Reranker ─────────────────────────────────────────────────────────────────

def load_rerank_model(device: str):
    log.info("Loading reranker %s ...", RERANK_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(RERANK_MODEL)
    model     = AutoModelForSequenceClassification.from_pretrained(RERANK_MODEL).to(device).eval()
    return tokenizer, model

def rerank(tokenizer, model, query: str, chunks: list[RetrievedChunk],
           device: str, batch_size: int = 8) -> list[RetrievedChunk]:
    """Score (query, chunk) pairs with the cross-encoder. Returns chunks sorted by score desc."""
    all_scores: list[float] = []
    pairs = [(query, c.chunk) for c in chunks]

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i : i + batch_size]
        encoded = tokenizer(
            batch, padding=True, truncation=True, max_length=8192, return_tensors="pt"
        ).to(device)
        with torch.no_grad():
            scores = model(**encoded, return_dict=True).logits.view(-1).float()
        all_scores.extend(scores.cpu().tolist())

    for chunk, score in zip(chunks, all_scores):
        chunk.rerank_score = score

    return sorted(chunks, key=lambda c: c.rerank_score, reverse=True)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )

def build_filter_clause(year: Optional[int], month: Optional[int],
                        company: Optional[str]) -> tuple[str, list]:
    """Return (WHERE clause fragment, params list). Empty string if no filters."""
    parts, params = [], []
    if year:
        parts.append("dc.year = %s")
        params.append(year)
    if month:
        parts.append("dc.month = %s")
        params.append(month)
    if company:
        parts.append("dc.company = %s")
        params.append(company)
    clause = "WHERE " + " AND ".join(parts) if parts else ""
    return clause, params


def bm25_search(conn, tsquery_str: str, filter_clause: str,
                filter_params: list, k: int) -> list[tuple[str, float]]:
    """Return [(doc_chunk_id, ts_rank_score)] ordered by rank desc."""
    if not tsquery_str:
        return []
    sql = f"""
        SELECT dc.doc_chunk_id,
               ts_rank(dc.tsv, to_tsquery('simple', %s)) AS score
        FROM document_chunks dc
        {filter_clause}
          {'AND' if filter_clause else 'WHERE'} dc.tsv @@ to_tsquery('simple', %s)
        ORDER BY score DESC
        LIMIT %s
    """
    params = [tsquery_str] + filter_params + [tsquery_str, k]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def vector_search(conn, vec: list[float], filter_clause: str,
                  filter_params: list, k: int) -> list[tuple[str, float]]:
    """Return [(doc_chunk_id, cosine_similarity)] ordered by similarity desc."""
    vec_str = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
    sql = f"""
        SELECT dc.doc_chunk_id,
               1 - (dc.embedding <=> %s::vector) AS score
        FROM document_chunks dc
        {filter_clause}
        ORDER BY dc.embedding <=> %s::vector
        LIMIT %s
    """
    params = [vec_str] + filter_params + [vec_str, k]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def rrf_fuse(bm25_results: list[tuple[str, float]],
             vec_results:  list[tuple[str, float]],
             c: int = RRF_C) -> list[tuple[str, float, Optional[int], Optional[int]]]:
    """
    Reciprocal rank fusion. Returns list of
    (doc_chunk_id, rrf_score, bm25_rank, vec_rank) sorted by rrf_score desc.
    """
    bm25_ranks = {cid: rank + 1 for rank, (cid, _) in enumerate(bm25_results)}
    vec_ranks  = {cid: rank + 1 for rank, (cid, _) in enumerate(vec_results)}
    all_ids    = set(bm25_ranks) | set(vec_ranks)

    scored = []
    for cid in all_ids:
        rrf = 0.0
        if cid in bm25_ranks:
            rrf += 1.0 / (c + bm25_ranks[cid])
        if cid in vec_ranks:
            rrf += 1.0 / (c + vec_ranks[cid])
        scored.append((cid, rrf, bm25_ranks.get(cid), vec_ranks.get(cid)))

    return sorted(scored, key=lambda x: x[1], reverse=True)


def fetch_chunks(conn, chunk_ids: list[str]) -> dict[str, RetrievedChunk]:
    """Fetch full chunk rows + meeting_date from documents for the given IDs."""
    sql = """
        SELECT
            dc.doc_chunk_id, dc.doc_id, dc.chunk, dc.chunk_type,
            dc.company, dc.dept, dc.section, dc.doc_type, dc.year, dc.month,
            d.meeting_date
        FROM document_chunks dc
        LEFT JOIN documents d ON d.doc_id = dc.doc_id
        WHERE dc.doc_chunk_id = ANY(%s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (chunk_ids,))
        rows = cur.fetchall()

    result = {}
    for row in rows:
        (cid, doc_id, chunk, chunk_type, company, dept, section,
         doc_type, year, month, meeting_date) = row
        result[cid] = RetrievedChunk(
            doc_chunk_id=cid, doc_id=doc_id, chunk=chunk, chunk_type=chunk_type,
            company=company, dept=dept, section=section, doc_type=doc_type,
            year=year, month=month,
            meeting_date=str(meeting_date) if meeting_date else None,
            bm25_rank=None, vec_rank=None, rrf_score=0.0, rerank_score=None,
        )
    return result


# ─── Main retrieval function ──────────────────────────────────────────────────

def retrieve(
    query:      str,
    embed_tok,
    embed_mod,
    rerank_tok,
    rerank_mod,
    sudachi_tok,
    device:     str,
    year:       Optional[int]  = None,
    month:      Optional[int]  = None,
    company:    Optional[str]  = None,
    top_k:      int            = FINAL_K,
    no_rerank:  bool           = False,
) -> list[RetrievedChunk]:
    # 1. Temporal from query if not explicit
    q_year, q_month = parse_temporal(query)
    eff_year  = year  if year  is not None else q_year
    eff_month = month if month is not None else q_month

    if eff_year or eff_month:
        log.info("Temporal filter: year=%s month=%s", eff_year, eff_month)

    filter_clause, filter_params = build_filter_clause(eff_year, eff_month, company)

    # 2. Embed query
    log.info("Embedding query ...")
    vec = embed_query(embed_tok, embed_mod, query, device)

    # 3. Tokenize query for BM25
    tokens = tokenize_query(sudachi_tok, query)
    log.info("Query tokens: %s", tokens)
    tsquery_str = build_tsquery(tokens)

    conn = get_conn()

    # 4. BM25 search
    bm25_results = bm25_search(conn, tsquery_str, filter_clause, list(filter_params), BM25_K)
    log.info("BM25 hits: %d", len(bm25_results))

    # 5. Vector search
    vec_results = vector_search(conn, vec, filter_clause, list(filter_params), VEC_K)
    log.info("Vector hits: %d", len(vec_results))

    # 6. RRF fusion
    fused = rrf_fuse(bm25_results, vec_results)
    rrf_top = fused[:RRF_K]
    log.info("RRF pool: %d → top %d to reranker", len(fused), len(rrf_top))

    # 7. Fetch chunk data
    top_ids = [cid for cid, _, _, _ in rrf_top]
    chunks_map = fetch_chunks(conn, top_ids)
    conn.close()

    # Attach RRF metadata
    candidates: list[RetrievedChunk] = []
    for cid, rrf_score, bm25_rank, vec_rank in rrf_top:
        if cid not in chunks_map:
            continue
        c = chunks_map[cid]
        c.rrf_score = rrf_score
        c.bm25_rank = bm25_rank
        c.vec_rank  = vec_rank
        candidates.append(c)

    # 8. Rerank
    if no_rerank or not candidates:
        return candidates[:top_k]

    log.info("Reranking %d candidates ...", len(candidates))
    reranked = rerank(rerank_tok, rerank_mod, query, candidates, device)
    return reranked[:top_k]


# ─── Two-phase API for eval ablation (shared BM25+vector+RRF, branch at rerank) ──

def retrieve_rrf_pool(
    query:      str,
    embed_tok,
    embed_mod,
    sudachi_tok,
    device:     str,
    year:       Optional[int] = None,
    month:      Optional[int] = None,
    company:    Optional[str] = None,
) -> list[RetrievedChunk]:
    """Runs embed + BM25 + vector + RRF. Returns top RRF_K candidates (no reranking)."""
    q_year, q_month = parse_temporal(query)
    eff_year  = year  if year  is not None else q_year
    eff_month = month if month is not None else q_month
    if eff_year or eff_month:
        log.info("Temporal filter: year=%s month=%s", eff_year, eff_month)

    filter_clause, filter_params = build_filter_clause(eff_year, eff_month, company)
    log.info("Embedding query ...")
    vec = embed_query(embed_tok, embed_mod, query, device)

    tokens = tokenize_query(sudachi_tok, query)
    log.info("Query tokens: %s", tokens)
    tsquery_str = build_tsquery(tokens)

    conn = get_conn()
    bm25_results = bm25_search(conn, tsquery_str, filter_clause, list(filter_params), BM25_K)
    log.info("BM25 hits: %d", len(bm25_results))
    vec_results  = vector_search(conn, vec, filter_clause, list(filter_params), VEC_K)
    log.info("Vector hits: %d", len(vec_results))

    fused   = rrf_fuse(bm25_results, vec_results)
    rrf_top = fused[:RRF_K]
    log.info("RRF pool: %d candidates", len(rrf_top))

    top_ids    = [cid for cid, _, _, _ in rrf_top]
    chunks_map = fetch_chunks(conn, top_ids)
    conn.close()

    candidates: list[RetrievedChunk] = []
    for cid, rrf_score, bm25_rank, vec_rank in rrf_top:
        if cid not in chunks_map:
            continue
        c = chunks_map[cid]
        c.rrf_score = rrf_score
        c.bm25_rank = bm25_rank
        c.vec_rank  = vec_rank
        candidates.append(c)
    return candidates


def finish_retrieve(
    query:      str,
    pool:       list[RetrievedChunk],
    rerank_tok,
    rerank_mod,
    device:     str,
    top_k:      int  = FINAL_K,
    no_rerank:  bool = False,
) -> list[RetrievedChunk]:
    """Takes a pre-computed RRF pool and returns top_k after optional reranking."""
    if no_rerank or not pool:
        return pool[:top_k]
    log.info("Reranking %d candidates ...", len(pool))
    reranked = rerank(rerank_tok, rerank_mod, query, pool, device)
    return reranked[:top_k]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid retrieval for Kyoritsu RAG")
    parser.add_argument("query", help="Natural language query (Japanese)")
    parser.add_argument("--year",      type=int,   default=None)
    parser.add_argument("--month",     type=int,   default=None)
    parser.add_argument("--company",   type=str,   default=None,
                        help="Filter by company (e.g. '共立電機製作所')")
    parser.add_argument("--top-k",     type=int,   default=FINAL_K,
                        dest="top_k")
    parser.add_argument("--no-rerank", action="store_true",
                        help="Skip reranker (faster, lower quality)")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    embed_tok, embed_mod   = load_embed_model(device)
    rerank_tok, rerank_mod = (None, None) if args.no_rerank else load_rerank_model(device)
    sudachi_tok            = build_sudachi()

    results = retrieve(
        query       = args.query,
        embed_tok   = embed_tok,
        embed_mod   = embed_mod,
        rerank_tok  = rerank_tok,
        rerank_mod  = rerank_mod,
        sudachi_tok = sudachi_tok,
        device      = device,
        year        = args.year,
        month       = args.month,
        company     = args.company,
        top_k       = args.top_k,
        no_rerank   = args.no_rerank,
    )

    print(f"\n{'='*70}")
    print(f"Query: {args.query}")
    print(f"Results: {len(results)}")
    print(f"{'='*70}\n")

    for i, r in enumerate(results, 1):
        print(f"[{i}] {r.doc_chunk_id}")
        print(f"    Company : {r.company}  Dept: {r.dept}  Date: {r.meeting_date or f'{r.year}-{r.month:02d}'}")
        print(f"    Type    : {r.chunk_type}  BM25-rank: {r.bm25_rank}  Vec-rank: {r.vec_rank}")
        print(f"    RRF     : {r.rrf_score:.5f}  Rerank: {r.rerank_score:.3f}" if r.rerank_score is not None
              else f"    RRF     : {r.rrf_score:.5f}")
        print(f"    Chunk   : {r.chunk[:300].replace(chr(10), ' ')}")
        print()


if __name__ == "__main__":
    main()
