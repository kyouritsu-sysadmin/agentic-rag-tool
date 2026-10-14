"""Behavioral regressions for the seven implementation-review defects."""

import asyncio
import os
import sys
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from kyoritsu_backend.schemas.documents import DocumentMetadata
from kyoritsu_backend.schemas.retrieval import RetrievalRequest
from kyoritsu_backend.core.settings import Settings
from kyoritsu_backend.rag.chunking import split_content
from kyoritsu_backend.rag.conversation import contextual_request
from kyoritsu_backend.workers import ingest


def user(text):
    return {"role": "user", "content": text}


def test_followup_chain_persists_context_and_resets():
    history = [user("共立電機製作所の2025年1月の売上"), user("では2月は？"), user("では3月は？")]
    resolved = contextual_request(history)
    assert resolved.company == "共立電機製作所"
    assert [(p.year, p.month) for p in resolved.periods] == [(2025, 3)]
    persisted = resolved.model_dump(mode="json")
    # Restart/history-window independent; a changed company and year take precedence.
    explicit = contextual_request([user("共立電照では2026年4月は？")], previous=persisted)
    assert explicit.company == "共立電照"
    assert [(p.year, p.month) for p in explicit.periods] == [(2026, 4)]
    reset = contextual_request([user("別の話題では採用について教えて")], previous=persisted)
    assert reset.company is None and reset.periods is None
    independent = contextual_request([user("採用について教えて")], previous=persisted)
    assert independent.company is None and independent.periods is None


def test_metadata_aliases_and_invalid_org_relationships():
    metadata = DocumentMetadata(
        company="denki",
        dept="本社営業",
        year=2025,
        month=1,
        import_key="metadata-001",
        doc_type="月報",
    )
    assert metadata.company == "共立電機製作所" and metadata.dept == "営業部"
    assert metadata.doc_type == "monthly_report"
    request = RetrievalRequest(query="sales", company="denki", dept="本社営業")
    assert request.company == metadata.company and request.dept == metadata.dept
    for fields in [
        dict(dept="営業部", section="加工課"),
        dict(dept="bogus"),
        dict(dept="営業部", section="営業-東京"),
    ]:
        with pytest.raises(ValidationError):
            DocumentMetadata(**{**metadata.model_dump(), **fields})


async def test_every_table_fragment_retains_header_and_content():
    async def count(text):
        return len(text)

    header = "| region | value |\n|---|---|"
    row = "| Tokyo | " + "x" * 1500 + " |"
    chunks = await split_content(
        "# Sales\nintro\n"
        + header
        + "\n"
        + row
        + "\nafter\n| year | total |\n|---|---|\n| 2025 | 42 |",
        count,
    )
    sales = [c for c in chunks if "region" in c["text"]]
    prefix = "# Sales\n" + header + "\n"
    assert len(sales) >= 3
    assert all(c["text"].startswith(prefix) and c["chunk_type"] == "table" for c in sales)
    assert "".join(c["text"][len(prefix) :] for c in sales) == row
    assert all(len(c["text"]) <= 600 for c in chunks)
    assert any(c["chunk_type"] == "text" and "after" in c["text"] for c in chunks)
    totals = [c for c in chunks if "year | total" in c["text"]]
    assert len(totals) == 1 and "region" not in totals[0]["text"]
    with pytest.raises(ValueError, match="header exceeds"):
        await split_content("|" + "h" * 700 + "|\n|---|\n| value |", count)


@pytest.mark.parametrize("cancel", [False, True])
async def test_hung_parser_is_killed_and_next_parse_succeeds(tmp_path, cancel):
    pidfile = tmp_path / "parser.pid"
    command = [
        sys.executable,
        "-c",
        "import os,sys,time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)",
        str(pidfile),
    ]
    task = asyncio.create_task(ingest.run_parser(command, 10 if cancel else 0.5))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.01)
    pid = int(pidfile.read_text())
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    document = tmp_path / "ok.txt"
    document.write_text("next document")
    assert await ingest.parse_pages(
        document,
        Settings(
            _env_file=None,
        ),
    ) == [[1, "next document"]]


async def test_worker_retries_claim_failure_and_remains_cancellable(monkeypatch):
    recovered = asyncio.Event()
    calls = 0

    async def process(*args):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise OperationalError("claim", {}, ConnectionError("database unavailable"))
        recovered.set()
        return False

    monkeypatch.setattr(ingest, "process_one", process)
    task = asyncio.create_task(
        ingest.worker_loop(None, None, Settings(_env_file=None, worker_retry_max_seconds=0.01))
    )
    await asyncio.wait_for(recovered.wait(), 2)
    assert calls == 3 and not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
