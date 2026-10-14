import asyncio
import pytest
from pydantic import ValidationError
from kyoritsu_backend.core.errors import ApplicationError
from kyoritsu_backend.schemas.retrieval import RetrievalRequest
from kyoritsu_backend.core.auth import Principal
from kyoritsu_backend.core.settings import Settings
from kyoritsu_backend.rag.planning import plan, extract_periods
from kyoritsu_backend.rag.fusion import fuse
from kyoritsu_backend.rag.chunking import split_content
from kyoritsu_backend.providers.models import ModelProvider

P = Principal("reader", ("A", "B"))


@pytest.mark.parametrize(
    "query,expected",
    [
        ("2025年", [(2025, None)]),
        ("2025年1月と2026年1月", [(2025, 1), (2026, 1)]),
        ("２０２７年２月と３月", [(2027, 2), (2027, 3)]),
        ("1月", [(None, 1)]),
    ],
)
def test_periods(query, expected):
    assert [(p.year, p.month) for p in extract_periods(query)] == expected


def test_omitted_company_and_override():
    scopes = plan(RetrievalRequest(query="2025年1月と2月", year=2027), P)
    assert {(s["company"], s["year"], s["month"]) for s in scopes} == {
        ("A", 2027, 1),
        ("A", 2027, 2),
        ("B", 2027, 1),
        ("B", 2027, 2),
    }
    with pytest.raises(ApplicationError):
        plan(RetrievalRequest(query="sales", company="C"), P)


@pytest.mark.parametrize(
    "kwargs", [{"query": " "}, {"query": "ok", "month": 13}, {"query": "ok", "top_k": 51}]
)
def test_validation(kwargs):
    with pytest.raises(ValidationError):
        RetrievalRequest(**kwargs)


def test_tie_order():
    assert [i for i, _ in fuse(["b", "a"], ["a", "b"])] == ["a", "b"]


async def test_long_chunks():
    async def count(s):
        return len(s)

    chunks = await split_content(
        "# Report\n" + "長い文章。" * 1000 + "\n| A | B |\n|---|---|\n" + "|長い行|値|" * 500, count
    )
    assert len(chunks) > 10
    assert all(len(c["text"]) <= 600 for c in chunks)
    assert "長い文章" in "".join(c["text"] for c in chunks)


async def test_cancel_does_not_release_executor_capacity():
    import threading

    settings = Settings(
        _env_file=None, model_backend="test", allow_test_provider=True, max_model_queue=1
    )
    model = ModelProvider(settings)
    release = threading.Event()
    task = asyncio.create_task(model.call(release.wait))
    await asyncio.sleep(0.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert model.pending == 1
    with pytest.raises(ApplicationError):
        await model.tokens("queued")
    release.set()
    await model.close()


def test_followup_preserves_period_and_overrides_company():
    from kyoritsu_backend.rag.conversation import contextual_request

    request = contextual_request(
        [
            {"role": "user", "content": "共立電機製作所 2025年1月 売上"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "共立電照では2月は？"},
        ]
    )
    scopes = plan(request, Principal("user", ("共立電機製作所", "共立電照")))
    assert {s["company"] for s in scopes} == {"共立電照"}
    assert {(s["year"], s["month"]) for s in scopes} == {(2025, 2)}
