# pyrefly: ignore [missing-import]
"""
api/app/retrieve.py — Async retrieval logic for the API layer.

Differences from retrieval/retrieve.py:
  - DB calls use asyncpg (non-blocking, $N params)
  - BM25 + vector searches run concurrently via asyncio.gather
  - GPU calls (embed, rerank) run in ThreadPoolExecutor(max_workers=1)
  - Accepts an asyncpg pool + executor injected from app.state
"""
import asyncio
import functools
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import asyncpg

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "retrieval"))  # for bare `from filters import ...` in retrieve.py

from retrieval.retrieve import (
    RetrievedChunk,
    BM25_K, VEC_K, RRF_K, FINAL_K,
    embed_query, rrf_fuse, rerank,
    tokenize_query, build_tsquery,
)
from retrieval.filters import taxonomy_pass

log = logging.getLogger(__name__)


# ─── Filter clause builder (asyncpg $N style) ────────────────────────────────

def _build_filter_clause(
    year:     Optional[int] = None,
    month:    Optional[int] = None,
    company:  Optional[str] = None,
    dept:     Optional[str] = None,
    section:  Optional[str] = None,
    doc_type: Optional[str] = None,
) -> tuple[str, list]:
    parts, params = [], []
    for col, val in [
        ("dc.year",     year),
        ("dc.month",    month),
        ("dc.company",  company),
        ("dc.dept",     dept),
        ("dc.section",  section),
        ("dc.doc_type", doc_type),
    ]:
        if val is not None:
            params.append(val)
            parts.append(f"{col} = ${len(params)}")
    clause = "WHERE " + " AND ".join(parts) if parts else ""
    return clause, params


# ─── Async DB queries ─────────────────────────────────────────────────────────

async def _bm25_search(
    pool: asyncpg.Pool,
    tsquery_str: str,
    filter_clause: str,
    filter_params: list,
    k: int,
) -> list[tuple[str, float]]:
    if not tsquery_str:
        return []
    n = len(filter_params)
    sql = f"""
        SELECT dc.doc_chunk_id,
               ts_rank(dc.tsv, to_tsquery('simple', ${n + 1})) AS score
        FROM document_chunks dc
        {filter_clause}
          {'AND' if filter_clause else 'WHERE'} dc.tsv @@ to_tsquery('simple', ${n + 2})
        ORDER BY score DESC
        LIMIT ${n + 3}
    """
    rows = await pool.fetch(sql, *filter_params, tsquery_str, tsquery_str, k)
    return [(r["doc_chunk_id"], float(r["score"])) for r in rows]


async def _vector_search(
    pool: asyncpg.Pool,
    vec: list[float],
    filter_clause: str,
    filter_params: list,
    k: int,
) -> list[tuple[str, float]]:
    vec_str = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
    n = len(filter_params)
    sql = f"""
        SELECT dc.doc_chunk_id,
               1 - (dc.embedding <=> ${n + 1}::vector) AS score
        FROM document_chunks dc
        {filter_clause}
        ORDER BY dc.embedding <=> ${n + 2}::vector
        LIMIT ${n + 3}
    """
    rows = await pool.fetch(sql, *filter_params, vec_str, vec_str, k)
    return [(r["doc_chunk_id"], float(r["score"])) for r in rows]


async def _fetch_chunks(
    pool: asyncpg.Pool,
    chunk_ids: list[str],
) -> dict[str, RetrievedChunk]:
    sql = """
        SELECT
            dc.doc_chunk_id, dc.doc_id, dc.chunk, dc.chunk_type,
            dc.company, dc.dept, dc.section, dc.doc_type, dc.year, dc.month,
            d.meeting_date
        FROM document_chunks dc
        LEFT JOIN documents d ON d.doc_id = dc.doc_id
        WHERE dc.doc_chunk_id = ANY($1)
    """
    rows = await pool.fetch(sql, chunk_ids)
    result = {}
    for r in rows:
        cid = r["doc_chunk_id"]
        result[cid] = RetrievedChunk(
            doc_chunk_id = cid,
            doc_id       = r["doc_id"],
            chunk        = r["chunk"],
            chunk_type   = r["chunk_type"],
            company      = r["company"],
            dept         = r["dept"],
            section      = r["section"],
            doc_type     = r["doc_type"],
            year         = r["year"],
            month        = r["month"],
            meeting_date = str(r["meeting_date"]) if r["meeting_date"] else None,
            bm25_rank    = None,
            vec_rank     = None,
            rrf_score    = 0.0,
            rerank_score = None,
        )
    return result


# ─── Main async retrieve ──────────────────────────────────────────────────────

async def retrieve_async(
    query:           str,
    pool:            asyncpg.Pool,
    embed_executor:  ThreadPoolExecutor,
    rerank_executor: ThreadPoolExecutor,
    embed_tok,
    embed_mod,
    rerank_tok,
    rerank_mod,
    sudachi_tok,
    device:          str,
    year:       Optional[int] = None,
    month:      Optional[int] = None,
    company:    Optional[str] = None,
    dept:       Optional[str] = None,
    section:    Optional[str] = None,
    doc_type:   Optional[str] = None,
    top_k:      int           = FINAL_K,
    no_rerank:  bool          = False,
) -> tuple[list[RetrievedChunk], dict]:
    """Returns (chunks, stage_timings) where stage_timings is a dict of ms per stage."""
    import time as _time
    loop = asyncio.get_event_loop()
    t = _time.perf_counter

    t0 = t()

    # Resolve unspecified filters from query text
    tax          = taxonomy_pass(query)
    eff_year     = year     if year     is not None else (tax["periods"][0][0] if tax["periods"]   else None)
    eff_month    = month    if month    is not None else (tax["periods"][0][1] if tax["periods"]   else None)
    eff_company  = company  if company  is not None else (tax["companies"][0]  if tax["companies"] else None)
    eff_dept     = dept     if dept     is not None else (tax["depts"][0]      if tax["depts"]     else None)
    eff_section  = section  if section  is not None else (tax["sections"][0]   if tax["sections"]  else None)
    eff_doc_type = doc_type if doc_type is not None else (tax["doc_types"][0]  if tax["doc_types"] else None)

    filter_clause, filter_params = _build_filter_clause(
        eff_year, eff_month, eff_company, eff_dept, eff_section, eff_doc_type
    )
    t_tax = t()

    # GPU: embed — serialized through embed_executor
    vec = await loop.run_in_executor(
        embed_executor,
        embed_query, embed_tok, embed_mod, query, device,
    )
    t_embed = t()

    # Tokenize for BM25 (sync, fast)
    tokens      = tokenize_query(sudachi_tok, query)
    tsquery_str = build_tsquery(tokens)

    # DB: BM25 + vector concurrently
    bm25_results, vec_results = await asyncio.gather(
        _bm25_search(pool, tsquery_str, filter_clause, list(filter_params), BM25_K),
        _vector_search(pool, vec, filter_clause, list(filter_params), VEC_K),
    )
    t_db_search = t()

    fused   = rrf_fuse(bm25_results, vec_results)
    rrf_top = fused[:RRF_K]

    if not rrf_top:
        return [], {"taxonomy_ms": 0, "embed_ms": 0, "db_search_ms": 0,
                    "fetch_ms": 0, "rerank_ms": 0, "total_ms": 0}

    # DB: fetch full chunk rows
    top_ids    = [cid for cid, _, _, _ in rrf_top]
    chunks_map = await _fetch_chunks(pool, top_ids)
    t_fetch = t()

    candidates: list[RetrievedChunk] = []
    for cid, rrf_score, bm25_rank, vec_rank in rrf_top:
        if cid not in chunks_map:
            continue
        c            = chunks_map[cid]
        c.rrf_score  = rrf_score
        c.bm25_rank  = bm25_rank
        c.vec_rank   = vec_rank
        candidates.append(c)

    if no_rerank or not candidates:
        timings = {
            "taxonomy_ms":  round((t_tax       - t0)         * 1000, 1),
            "embed_ms":     round((t_embed      - t_tax)      * 1000, 1),
            "db_search_ms": round((t_db_search  - t_embed)    * 1000, 1),
            "fetch_ms":     round((t_fetch      - t_db_search)* 1000, 1),
            "rerank_ms":    0,
            "total_ms":     round((t_fetch      - t0)         * 1000, 1),
        }
        return candidates[:top_k], timings

    # GPU: rerank — serialized through rerank_executor
    reranked = await loop.run_in_executor(
        rerank_executor,
        functools.partial(rerank, rerank_tok, rerank_mod, query, candidates, device),
    )
    t_rerank = t()

    timings = {
        "taxonomy_ms":  round((t_tax        - t0)          * 1000, 1),
        "embed_ms":     round((t_embed       - t_tax)       * 1000, 1),
        "db_search_ms": round((t_db_search   - t_embed)     * 1000, 1),
        "fetch_ms":     round((t_fetch       - t_db_search) * 1000, 1),
        "rerank_ms":    round((t_rerank      - t_fetch)     * 1000, 1),
        "total_ms":     round((t_rerank      - t0)          * 1000, 1),
    }
    return reranked[:top_k], timings
