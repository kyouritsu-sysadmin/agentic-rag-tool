# pyrefly: ignore [missing-import]
import asyncio
import logging
import time

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Request

from api.app.config import REQUEST_TIMEOUT
from api.app.schema import ChunkOut, FiltersApplied, RetrieveRequest, RetrieveResponse
from api.app.retrieve import retrieve_async

router = APIRouter()
log    = logging.getLogger(__name__)


@router.post("/v1/tool/retrieval", response_model=RetrieveResponse)
async def retrieval(body: RetrieveRequest, req: Request):
    s = req.app.state
    filters_str = (
        f"company={body.company} dept={body.dept} section={body.section} "
        f"year={body.year} month={body.month} doc_type={body.doc_type} "
        f"top_k={body.top_k} no_rerank={body.no_rerank}"
    )
    log.info("POST /v1/tool/retrieval | query=%r | %s", body.query, filters_str)
    t0 = time.perf_counter()

    try:
        chunks, timings = await asyncio.wait_for(
            retrieve_async(
                query          = body.query,
                pool           = s.db_pool,
                embed_executor = s.embed_executor,
                rerank_executor= s.rerank_executor,
                embed_tok      = s.embed_tok,
                embed_mod   = s.embed_mod,
                rerank_tok  = s.rerank_tok,
                rerank_mod  = s.rerank_mod,
                sudachi_tok = s.sudachi,
                device      = s.device,
                year        = body.year,
                month       = body.month,
                company     = body.company,
                dept        = body.dept,
                section     = body.section,
                doc_type    = body.doc_type,
                top_k       = body.top_k,
                no_rerank   = body.no_rerank,
            ),
            timeout=REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning("504 | query=%r | timed out after %.0fs", body.query, REQUEST_TIMEOUT)
        raise HTTPException(status_code=504, detail="Retrieval timed out")

    elapsed = time.perf_counter() - t0
    log.info(
        "200 | chunks=%d | total=%.2fs | "
        "tax=%.0fms embed=%.0fms db=%.0fms fetch=%.0fms rerank=%.0fms",
        len(chunks), elapsed,
        timings["taxonomy_ms"], timings["embed_ms"],
        timings["db_search_ms"], timings["fetch_ms"], timings["rerank_ms"],
    )

    eff = timings.get("eff_filters", {})
    return RetrieveResponse(
        chunks          = [ChunkOut(**vars(c)) for c in chunks],
        count           = len(chunks),
        filters_applied = FiltersApplied(
            company  = eff.get("company"),
            dept     = eff.get("dept"),
            section  = eff.get("section"),
            year     = eff.get("year"),
            month    = eff.get("month"),
            doc_type = eff.get("doc_type"),
        ),
    )


@router.get("/v1/health")
async def health():
    return {"status": "ok"}
