"""Verify the real persistence/retrieval path works without external model calls."""

import httpx
import pytest
from kyoritsu_backend.workers.ingest import process_one
from tests.support import DSN, upload, wait_run

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="Requires a disposable migrated PostgreSQL database"),
]


async def test_mock_pipeline_includes_reranking_without_external_http(application, monkeypatch):
    app, client = application
    attempted_http = []

    async def forbid_http(self, request):
        attempted_http.append(request.url.host)
        raise AssertionError("Simulation attempted an external model call")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid_http)
    app.state.settings.ollama_url = "http://127.0.0.1:9"
    app.state.settings.enable_rerank = True
    reranked = []
    original = app.state.models.rerank

    async def record_reranking(query, chunks):
        reranked.append(len(chunks))
        return await original(query, chunks)

    monkeypatch.setattr(app.state.models, "rerank", record_reranking)
    job = await upload(client, key="mock-offline-flow")
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    assert (await client.get(f"/v1/jobs/{job['job_id']}")).json()["status"] == "completed"
    thread = (await client.post("/v1/threads", json={})).json()["id"]
    submitted = await client.post(
        f"/v1/threads/{thread}/messages",
        json={"text": "2025年1月 sales", "idempotency_key": "mock-reranked-answer"},
    )
    assert submitted.status_code == 202
    result = await wait_run(client, submitted.json()["id"])
    assert result["status"] == "completed", result
    assert result["message"]["text"].startswith("[TEST PROVIDER]")
    assert result["message"]["citations"]
    assert reranked and all(count > 0 for count in reranked)
    assert attempted_http == []
    assert (await client.get("/health/ready")).status_code == 200


async def test_summary_persistence_failure_and_index_configuration(application, monkeypatch):
    from sqlalchemy import select
    from kyoritsu_backend.db.models import Chunk, DocumentVersion
    from kyoritsu_backend.workers import ingest

    app, client = application
    job = await upload(client, key="summarized-source")
    wrong_worker = app.state.settings.model_copy(update={"embed_revision": "different"})
    await process_one(app.state.sessions, app.state.models, wrong_worker)
    status = (await client.get(f"/v1/jobs/{job['job_id']}")).json()
    assert status["status"] == "failed" and "configuration" in status["error"]
    assert (await client.post(f"/v1/jobs/{job['job_id']}/retry")).status_code == 200
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    status = (await client.get(f"/v1/jobs/{job['job_id']}")).json()
    assert status["status"] == "completed"
    async with app.state.sessions() as session:
        chunks = (
            await session.scalars(select(Chunk).where(Chunk.version_id == job["version_id"]))
        ).all()
        assert chunks and all(c.summary.startswith("[TEST SUMMARY]") for c in chunks)
        version = await session.get(DocumentVersion, job["version_id"])
        assert version.pipeline["requested"]["summary_model"] == app.state.settings.summary_model
    replacement = await upload(
        client, key="failed-summary", document_id=status["document_id"], content="changed text"
    )

    async def unavailable(*args):
        raise RuntimeError("summary provider unavailable")

    monkeypatch.setattr(ingest, "summarize", unavailable)
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    assert (await client.get(f"/v1/jobs/{replacement['job_id']}")).json()["status"] == "failed"
    docs = (await client.get("/v1/documents")).json()["documents"]
    assert (
        next(d for d in docs if d["id"] == status["document_id"])["active_version_id"]
        == job["version_id"]
    )
