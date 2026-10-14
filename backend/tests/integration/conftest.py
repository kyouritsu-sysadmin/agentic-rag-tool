"""Only run against a disposable migrated PostgreSQL database supplied explicitly."""

import pytest
import httpx
from sqlalchemy import text
from kyoritsu_backend.main import create_app
from kyoritsu_backend.core.settings import Settings
from kyoritsu_backend.db.session import create_database

from tests.support import DSN, TOKEN, OTHER


@pytest.fixture
async def application(tmp_path):
    engine, sessions = create_database(DSN)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE message_sources, generation_runs, messages, threads, ingestion_jobs, document_chunks, document_versions, documents CASCADE"
            )
        )
    await engine.dispose()
    settings = Settings(
        _env_file=None,
        database_url=DSN,
        storage_dir=tmp_path,
        model_backend="test",
        allow_test_provider=True,
        credentials=[
            dict(token=TOKEN, subject="alice", companies=["A"], admin=True),
            dict(token=OTHER, subject="bob", companies=["B"], admin=True),
        ],
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client:
            yield app, client
