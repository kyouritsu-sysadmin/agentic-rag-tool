"""Test-only server with a durable ingestion worker; requires a disposable database."""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch
from kyoritsu_backend.main import create_app
from kyoritsu_backend.core.settings import Settings
from tests.database_safety import disposable_database_url

settings = Settings(
    _env_file=None,
    database_url=disposable_database_url(os.environ["RAG_TEST_DATABASE_URL"]),
    storage_dir=Path("/tmp/nw-rag-browser-sources"),
    model_backend="test",
    allow_test_provider=True,
    enable_rerank=True,
    ollama_url="http://127.0.0.1:9",
    cors_origins=["http://127.0.0.1:3018"],
    credentials=[
        dict(
            token="browser-admin-token-00001", subject="browser-alice", companies=["A"], admin=True
        ),
        dict(token="browser-reader-token-0002", subject="browser-bob", companies=["B"]),
    ],
)
app = create_app(settings)
base_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(app):
    # A simulation must fail rather than silently contact a real answer provider.
    with (
        patch(
            "httpx.AsyncHTTPTransport.handle_async_request",
            side_effect=AssertionError("External HTTP is forbidden in the browser fixture"),
        ),
        patch(
            "httpx.HTTPTransport.handle_request",
            side_effect=AssertionError("External HTTP is forbidden in the browser fixture"),
        ),
    ):
        async with base_lifespan(app):
            worker = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "tests.e2e.worker_server",
                cwd=Path(__file__).resolve().parents[2],
            )
            try:
                yield
            finally:
                if worker.returncode is None:
                    worker.terminate()
                try:
                    await asyncio.wait_for(worker.wait(), 10)
                except TimeoutError:
                    worker.kill()
                    await worker.wait()


app.router.lifespan_context = lifespan
