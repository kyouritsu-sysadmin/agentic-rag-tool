"""Only run against a disposable migrated PostgreSQL database supplied explicitly."""

import asyncio
import json
import pytest
import httpx
from sqlalchemy import text
from kyoritsu_backend.main import create_app
from kyoritsu_backend.core.settings import Settings
from kyoritsu_backend.db.session import create_database
from kyoritsu_backend.workers.ingest import process_one

from tests.support import DSN, TOKEN, OTHER, upload, wait_run

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN, reason="Set RAG_TEST_DATABASE_URL to a disposable migrated PostgreSQL database"
    ),
]


async def test_ingestion_retrieval_chat_branches_sources(application):
    app, client = application
    job = await upload(client)
    assert (await upload(client))["job_id"] == job["job_id"]
    assert await process_one(app.state.sessions, app.state.models, app.state.settings)
    status = (await client.get("/v1/jobs/" + job["job_id"])).json()
    assert status["status"] == "completed", status
    result = await client.post("/v1/tool/retrieval", json={"query": "2025年1月 sales", "top_k": 50})
    assert result.status_code == 200, result.text
    assert result.json()["count"] > 0
    assert (
        await client.post("/v1/tool/retrieval", json={"query": "sales", "company": "B"})
    ).status_code == 403
    thread = (await client.post("/v1/threads", json={})).json()["id"]
    payload = {"text": "2025年1月 sales", "idempotency_key": "request-0001"}
    submitted = await client.post(f"/v1/threads/{thread}/messages", json=payload)
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["id"]
    assert (await client.post(f"/v1/threads/{thread}/messages", json=payload)).json()[
        "id"
    ] == run_id
    assert (
        await client.post(f"/v1/threads/{thread}/messages", json={**payload, "text": "different"})
    ).status_code == 409
    completed = await wait_run(client, run_id)
    assert completed["status"] == "completed", completed
    assert completed["message"]["citations"]
    source = completed["message"]["citations"][0]["source_url"]
    assert (await client.get(source)).status_code == 200
    assert (
        await client.get(source, headers={"Authorization": f"Bearer {OTHER}"})
    ).status_code == 404
    assert (
        await client.get(
            f"/v1/threads/{thread}/messages", headers={"Authorization": f"Bearer {OTHER}"}
        )
    ).status_code == 404
    stream = await client.get(f"/v1/runs/{run_id}/events")
    assert '"type": "terminal"' in stream.text
    # Editing creates a second root and leaves the first branch intact.
    second = (
        await client.post(
            f"/v1/threads/{thread}/messages",
            json={**payload, "parent_id": None, "idempotency_key": "request-0002"},
        )
    ).json()
    await wait_run(client, second["id"])
    old = await client.get(
        f"/v1/threads/{thread}/messages", params={"head_id": completed["assistant_message_id"]}
    )
    assert len(old.json()["messages"]) == 2
    assert len((await client.get(f"/v1/threads/{thread}/branches")).json()["branches"]) == 2
    # Replacement does not invalidate the old citation source.
    newjob = await upload(
        client, key="import-0002", content="replacement content", document_id=status["document_id"]
    )
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    assert (await client.get("/v1/jobs/" + newjob["job_id"])).json()["status"] == "completed"
    assert (await client.get(source)).status_code == 200
    assert (await client.delete(f"/v1/threads/{thread}")).status_code == 204


async def test_cancel_auth_and_restart(application):
    app, client = application
    assert (await client.get("/v1/threads", headers={"Authorization": ""})).status_code == 401
    assert (await client.post("/v1/tool/retrieval", json={"query": " "})).status_code == 422
    assert (
        await client.post("/v1/tool/retrieval", json={"query": "2025年13月"})
    ).status_code == 422
    thread = (await client.post("/v1/threads", json={})).json()["id"]
    original = app.state.retrieval.retrieve
    started = asyncio.Event()

    async def slow(*args):
        started.set()
        await asyncio.sleep(20)
        return await original(*args)

    app.state.retrieval.retrieve = slow
    run = (
        await client.post(
            f"/v1/threads/{thread}/messages",
            json={"text": "sales", "idempotency_key": "cancel-test"},
        )
    ).json()
    await started.wait()
    assert (
        await client.post(
            f"/v1/threads/{thread}/messages",
            json={"text": "sales", "idempotency_key": "conflict-test"},
        )
    ).status_code == 409
    cancelled = await client.post(f"/v1/runs/{run['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    app.state.retrieval.retrieve = original
    assert (await client.get("/health/ready")).status_code == 503
    await client.post("/v1/models/warmup")
    assert (await client.get("/health/ready")).status_code == 200


async def test_failed_replacement_reindex_and_expired_lease(application):
    from datetime import timedelta
    from sqlalchemy import select
    from kyoritsu_backend.db.models import Document, IngestionJob, Chunk, now

    app, client = application
    job = await upload(client)
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    details = (await client.get("/v1/jobs/" + job["job_id"])).json()
    doc_id = details["document_id"]
    failed = await upload(client, key="failed-replacement", content="   ", document_id=doc_id)
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    assert (await client.get("/v1/jobs/" + failed["job_id"])).json()["status"] == "failed"
    async with app.state.sessions() as session:
        assert (await session.get(Document, doc_id)).active_version_id == job["version_id"]
    reindex = await client.post(f"/v1/documents/{doc_id}/reindex?import_key=reindex-001")
    assert reindex.status_code == 202, reindex.text
    # Simulate a crashed worker after claiming, then recover the expired lease.
    async with app.state.sessions.begin() as session:
        row = await session.get(IngestionJob, reindex.json()["job_id"])
        row.status, row.attempts, row.lease_token = "running", 1, "dead-worker"
        row.lease_until = now() - timedelta(seconds=10)
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    status = (await client.get("/v1/jobs/" + reindex.json()["job_id"])).json()
    assert status["status"] == "completed" and status["attempts"] == 2
    async with app.state.sessions() as session:
        doc = await session.get(Document, doc_id)
        assert doc.active_version_id == reindex.json()["version_id"]
        ids = (
            await session.scalars(
                select(Chunk.doc_chunk_id).where(Chunk.version_id == doc.active_version_id)
            )
        ).all()
        assert len(ids) == len(set(ids)) > 0


async def test_provider_failure_keeps_partial_output(application, monkeypatch):
    import kyoritsu_backend.services.chat as chat_module

    app, client = application

    async def broken(*args):
        yield "partial answer"
        raise RuntimeError("provider disconnected")

    monkeypatch.setattr(chat_module, "answer", broken)
    thread = (await client.post("/v1/threads", json={})).json()["id"]
    run = (
        await client.post(
            f"/v1/threads/{thread}/messages",
            json={"text": "question", "idempotency_key": "broken-provider"},
        )
    ).json()
    result = await wait_run(client, run["id"])
    assert result["status"] == "failed"
    assert result["message"]["text"] == "partial answer"
    assert result["message"]["status"] == "failed"


async def test_restart_recovers_orphan_and_single_api_guard(tmp_path):
    from kyoritsu_backend.db.models import Thread, Message, GenerationRun

    settings = Settings(
        _env_file=None,
        database_url=DSN,
        storage_dir=tmp_path,
        model_backend="test",
        allow_test_provider=True,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with app.state.sessions.begin() as session:
            thread = Thread(owner_id="restart-test")
            session.add(thread)
            await session.flush()
            user = Message(thread_id=thread.id, role="user", text="question")
            session.add(user)
            await session.flush()
            assistant = Message(
                thread_id=thread.id,
                parent_id=user.id,
                role="assistant",
                text="saved partial",
                status="running",
            )
            session.add(assistant)
            await session.flush()
            run = GenerationRun(
                thread_id=thread.id,
                user_message_id=user.id,
                assistant_message_id=assistant.id,
                idempotency_key="restart-test",
                request_hash="a" * 64,
                model_id="default",
                status="running",
            )
            session.add(run)
            await session.flush()
            run_id = run.id
        other = create_app(settings)
        with pytest.raises(RuntimeError, match="Another API process"):
            async with other.router.lifespan_context(other):
                pass
    restarted = create_app(settings)
    async with restarted.router.lifespan_context(restarted):
        async with restarted.state.sessions() as session:
            run = await session.get(GenerationRun, run_id)
            assert run.status == "interrupted"
            message = await session.get(Message, run.assistant_message_id)
            assert message.status == "interrupted" and message.text == "saved partial"


async def test_cross_year_coverage_and_upload_validation(application):
    app, client = application
    await upload(client, key="period-2025", year=2025)
    await upload(client, key="period-2026", year=2026)
    for _ in range(2):
        await process_one(app.state.sessions, app.state.models, app.state.settings)
    result = await client.post(
        "/v1/tool/retrieval", json={"query": "2025年1月と2026年1月 sales", "top_k": 2}
    )
    assert result.status_code == 200, result.text
    assert {c["year"] for c in result.json()["chunks"]} == {2025, 2026}
    assert all(scope["returned"] == 1 for scope in result.json()["coverage"])
    unsupported = await client.post(
        "/v1/documents",
        data={
            "metadata": json.dumps(
                {
                    "company": "A",
                    "dept": "sales",
                    "year": 2025,
                    "month": 1,
                    "import_key": "unsupported",
                }
            )
        },
        files={"file": ("bad.exe", b"content")},
    )
    assert unsupported.status_code == 415
    app.state.settings.max_upload_bytes = 32
    oversized = await client.post(
        "/v1/documents",
        data={
            "metadata": json.dumps(
                {
                    "company": "A",
                    "dept": "sales",
                    "year": 2025,
                    "month": 1,
                    "import_key": "oversized",
                }
            )
        },
        files={"file": ("big.txt", b"a" * 100)},
    )
    assert oversized.status_code == 413


async def test_alias_upload_retrieval_and_scope_authorization(application):
    from kyoritsu_backend.core.settings import Credential

    app, client = application
    app.state.settings.credentials.append(
        Credential(
            token="integration-japanese-token-003",
            subject="japanese-admin",
            companies=["共立電機製作所"],
            admin=True,
        )
    )
    client.headers["Authorization"] = "Bearer integration-japanese-token-003"
    job = await upload(client, company="denki", dept="本社営業")
    await process_one(app.state.sessions, app.state.models, app.state.settings)
    for dept in ["営業部", "本社営業"]:
        response = await client.post(
            "/v1/tool/retrieval",
            json={
                "query": "sales",
                "company": "denki",
                "dept": dept,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["count"] > 0
        assert {c["dept"] for c in response.json()["chunks"]} == {"営業部"}
    assert (await client.get("/v1/jobs/" + job["job_id"])).json()["status"] == "completed"
    denied = await client.post(
        "/v1/documents",
        data={
            "metadata": json.dumps(
                {
                    "company": "densho",
                    "dept": "営業部",
                    "year": 2025,
                    "month": 1,
                    "import_key": "denied-alias-upload",
                }
            )
        },
        files={"file": ("report.txt", b"sales")},
    )
    assert denied.status_code == 403
    invalid = await client.post(
        "/v1/documents",
        data={
            "metadata": json.dumps(
                {
                    "company": "denki",
                    "dept": "営業部",
                    "section": "加工課",
                    "year": 2025,
                    "month": 1,
                    "import_key": "invalid-org-upload",
                }
            )
        },
        files={"file": ("report.txt", b"sales")},
    )
    assert invalid.status_code == 422


async def test_parser_timeout_fails_job_and_worker_processes_next(application, monkeypatch):
    import sys
    from kyoritsu_backend.workers import ingest

    app, client = application
    first = await upload(client, key="hung-parser-job")
    second = await upload(client, key="next-parser-job")
    original = ingest.parse_pages
    calls = 0

    async def hung_once(path, settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            return await ingest.run_parser(
                [sys.executable, "-c", "import time;time.sleep(60)"], 0.1
            )
        return await original(path, settings)

    monkeypatch.setattr(ingest, "parse_pages", hung_once)
    for _ in range(2):
        assert await process_one(app.state.sessions, app.state.models, app.state.settings)
    assert (await client.get("/v1/jobs/" + first["job_id"])).json()["status"] == "failed"
    assert (await client.get("/v1/jobs/" + second["job_id"])).json()["status"] == "completed"


async def test_guard_loss_fences_old_api_and_allows_successor(application):
    from fastapi import HTTPException
    from kyoritsu_backend.db.models import GenerationRun

    app, client = application
    started = asyncio.Event()

    async def slow(*args):
        started.set()
        await asyncio.sleep(60)

    app.state.retrieval.retrieve = slow
    thread = (await client.post("/v1/threads", json={})).json()["id"]
    run = (
        await client.post(
            f"/v1/threads/{thread}/messages",
            json={
                "text": "sales",
                "idempotency_key": "guard-loss-test",
            },
        )
    ).json()
    await asyncio.wait_for(started.wait(), 2)
    engine, _ = create_database(DSN)
    try:
        async with engine.begin() as conn:
            assert await conn.scalar(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": app.state.ownership.pid}
            )
        successor = create_app(app.state.settings)
        async with successor.router.lifespan_context(successor):
            # Exercise transaction fencing directly, before relying on middleware/watchdog.
            with pytest.raises(HTTPException) as error:
                await app.state.chat.persist(run["id"], "stale output", "completed")
            assert error.value.status_code == 503
            assert (await client.post("/v1/threads", json={})).status_code == 503
            assert (await client.get("/health/ready")).status_code == 503
            async with successor.state.sessions() as session:
                saved = await session.get(GenerationRun, run["id"])
                assert saved.status == "interrupted"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=successor),
                base_url="http://test",
                headers=client.headers,
            ) as fresh:
                assert (await fresh.post("/v1/threads", json={})).status_code == 201
    finally:
        await engine.dispose()


async def test_context_survives_long_history_restart_and_branch(tmp_path):
    from kyoritsu_backend.db.models import GenerationRun

    settings = Settings(
        _env_file=None,
        database_url=DSN,
        storage_dir=tmp_path,
        model_backend="test",
        allow_test_provider=True,
        credentials=[
            dict(
                token=TOKEN,
                subject="context-test",
                companies=["共立電機製作所", "共立電照"],
                admin=True,
            )
        ],
    )
    first_head = None
    thread = None
    for restart in range(2):
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {TOKEN}"},
            ) as client:
                if not restart:
                    thread = (await client.post("/v1/threads", json={})).json()["id"]
                turns = range(1, 9) if not restart else [9, 10]
                for month in turns:
                    query = (
                        "共立電機製作所の2025年1月の売上" if month == 1 else f"では{month}月は？"
                    )
                    payload = {"text": query, "idempotency_key": f"context-month-{month}"}
                    if month == 10:
                        payload["parent_id"] = first_head
                    response = await client.post(f"/v1/threads/{thread}/messages", json=payload)
                    assert response.status_code == 202, response.text
                    result = await wait_run(client, response.json()["id"])
                    assert result["status"] == "completed", result
                    if month == 1:
                        first_head = result["assistant_message_id"]
                    async with app.state.sessions() as session:
                        run = await session.get(GenerationRun, result["id"])
                        context = run.configuration["retrieval_request"]
                        assert context["company"] == "共立電機製作所"
                        assert context["periods"] == [{"year": 2025, "month": month}]
                        assert {s["company"] for s in run.configuration["retrieval"]["scopes"]} == {
                            "共立電機製作所"
                        }


async def test_worker_recovers_from_real_database_connection_failure(application):
    from sqlalchemy.engine import make_url
    from kyoritsu_backend.workers.ingest import worker_loop

    app, client = application
    job = await upload(client, key="database-outage-job")
    unavailable, failing = create_database(make_url(DSN).set(port=1))
    calls = 0

    class ReconnectingSessions:
        def begin(self):
            nonlocal calls
            calls += 1
            return (failing if calls == 1 else app.state.sessions).begin()

    app.state.settings.worker_retry_max_seconds = 0.01
    worker = asyncio.create_task(
        worker_loop(ReconnectingSessions(), app.state.models, app.state.settings)
    )
    try:
        for _ in range(100):
            status = (await client.get("/v1/jobs/" + job["job_id"])).json()
            if status["status"] == "completed":
                break
            await asyncio.sleep(0.03)
        assert status["status"] == "completed" and calls >= 2
        assert not worker.done()
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await unavailable.dispose()


async def test_heartbeat_failure_cancels_work_before_publication(application, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from kyoritsu_backend.workers import ingest

    app, client = application
    job = await upload(client, key="heartbeat-failure-job")
    cancelled = asyncio.Event()
    calls = 0

    class HeartbeatFails:
        def begin(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OperationalError("heartbeat", {}, ConnectionError("disconnected"))
            return app.state.sessions.begin()

    async def blocked_parser(*args):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(ingest, "parse_pages", blocked_parser)
    app.state.settings.job_lease_seconds = 0.06
    await asyncio.wait_for(process_one(HeartbeatFails(), app.state.models, app.state.settings), 2)
    assert cancelled.is_set()
    assert (await client.get("/v1/jobs/" + job["job_id"])).json()["status"] == "failed"
    assert (await client.get("/v1/documents")).json()["documents"][0]["active_version_id"] is None
