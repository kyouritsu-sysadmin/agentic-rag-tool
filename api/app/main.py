# pyrefly: ignore [missing-import]
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import torch
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.app.config import API_PORT, DB_DSN, DB_POOL_MIN, DB_POOL_MAX
from api.app.routes import router
from retrieval.retrieve import load_embed_model, load_rerank_model, build_sudachi

# ─── Logging — api/logs/api.log ───────────────────────────────────────────────

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_fmt     = logging.Formatter("%(levelname)s | %(message)s")
_handler = logging.FileHandler(_LOG_DIR / "api.log", encoding="utf-8")
_handler.setFormatter(_fmt)
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_handler, _console])
log = logging.getLogger(__name__)


# ─── Lifespan: load models + open DB pool once ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Device: %s", device)

    log.info("Loading embedding model ...")
    embed_tok, embed_mod = load_embed_model(device)

    log.info("Loading reranker ...")
    rerank_tok, rerank_mod = load_rerank_model(device)

    log.info("Building Sudachi tokenizer ...")
    sudachi_tok = build_sudachi()

    log.info("Opening DB pool (%s) ...", DB_DSN.split("@")[-1])
    db_pool = await asyncpg.create_pool(
        DB_DSN,
        min_size=DB_POOL_MIN,
        max_size=DB_POOL_MAX,
    )

    # Two separate executors: embed and rerank can overlap across requests
    embed_executor  = ThreadPoolExecutor(max_workers=1)
    rerank_executor = ThreadPoolExecutor(max_workers=1)

    app.state.device          = device
    app.state.embed_tok       = embed_tok
    app.state.embed_mod       = embed_mod
    app.state.rerank_tok      = rerank_tok
    app.state.rerank_mod      = rerank_mod
    app.state.sudachi         = sudachi_tok
    app.state.db_pool         = db_pool
    app.state.embed_executor  = embed_executor
    app.state.rerank_executor = rerank_executor

    log.info("API ready.")
    yield

    log.info("Shutting down ...")
    await db_pool.close()
    embed_executor.shutdown(wait=True)
    rerank_executor.shutdown(wait=True)


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Kyoritsu RAG Retriever", version="1.0.0", lifespan=lifespan)
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("api.app.main:app", host="0.0.0.0", port=API_PORT, workers=1)
