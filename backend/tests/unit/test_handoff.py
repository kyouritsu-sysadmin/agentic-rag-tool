"""Handoff regressions; no database or real model calls."""

from pathlib import Path
import pytest
from kyoritsu_backend.core.settings import Settings


def test_settings_ignore_working_directory_dotenv(monkeypatch, tmp_path):
    from kyoritsu_backend.core import settings as module

    config_dir = tmp_path / "backend"
    config_dir.mkdir()
    (config_dir / ".env").write_text("RAG_ANSWER_MODEL=project-model\n")
    monkeypatch.setattr(module, "CONFIG_DIR", config_dir)
    monkeypatch.delenv("RAG_ENV_FILE", raising=False)
    expected = Settings()
    (tmp_path / ".env").write_text("RAG_ANSWER_MODEL=unrelated-project\n")
    monkeypatch.chdir(tmp_path)
    actual = Settings()
    assert actual.answer_model == expected.answer_model
    assert actual.storage_dir == expected.storage_dir
    assert actual.storage_dir.is_absolute()


def test_explicit_config_resolves_relative_storage(monkeypatch, tmp_path):
    config = tmp_path / "deployment.env"
    config.write_text("RAG_STORAGE_DIR=sources\nRAG_ANSWER_MODEL=configured-answer\n")
    monkeypatch.setenv("RAG_ENV_FILE", str(config))
    monkeypatch.chdir(Path(__file__).parents[3])
    settings = Settings()
    assert settings.answer_model == "configured-answer"
    assert settings.storage_dir == tmp_path / "sources"


def test_cli_uses_documented_api_port(monkeypatch):
    from kyoritsu_backend.cli import main as cli

    observed = []

    async def capture(args):
        observed.append(args.url)

    monkeypatch.setattr(cli, "execute", capture)
    monkeypatch.setattr("sys.argv", ["rag-admin", "query", "sales"])
    cli.main()
    assert observed == ["http://localhost:8005"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://rag_test:x@localhost/rag",
        "postgresql+asyncpg://postgres:x@localhost/rag_test",
        "postgresql+asyncpg://rag_test:x@localhost/rag_test?database=rag",
    ],
)
def test_database_guard_rejects_application_targets(monkeypatch, url):
    from tests.database_safety import disposable_database_url

    monkeypatch.setenv("RAG_ALLOW_TEST_DATABASE_RESET", "1")
    with pytest.raises(ValueError):
        disposable_database_url(url)


def test_database_guard_requires_opt_in(monkeypatch):
    from tests.database_safety import disposable_database_url

    url = "postgresql+asyncpg://rag_test:x@localhost/rag_test_handoff"
    monkeypatch.delenv("RAG_ALLOW_TEST_DATABASE_RESET", raising=False)
    with pytest.raises(ValueError):
        disposable_database_url(url)
    monkeypatch.setenv("RAG_ALLOW_TEST_DATABASE_RESET", "1")
    assert disposable_database_url(url) == url


async def test_summary_provider_contract_and_failures(monkeypatch):
    import httpx
    from kyoritsu_backend.providers.summaries import summarize
    import json

    settings = Settings(_env_file=None)
    responses = [
        {"response": "Grounded summary", "done": True},
        {"response": "partial", "done": False},
        {"error": "unavailable"},
        {"response": "   ", "done": True},
    ]

    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/api/generate"
        assert body["model"] == "qcwind/qwen2.5-7B-instruct-Q4_K_M"
        assert "source text" in body["prompt"] and body["stream"] is False
        return httpx.Response(200, json=responses.pop(0))

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    assert await summarize(settings, "source text") == "Grounded summary"
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await summarize(settings, "source text")
    settings.enable_summary = False
    assert await summarize(settings, "source text") is None
    settings.enable_summary, settings.model_backend = True, "test"
    assert (await summarize(settings, "source text")).startswith("[TEST SUMMARY]")


def test_unpinned_models_rejected_before_indexing():
    from kyoritsu_backend.rag.pipeline import indexing_configuration

    settings = Settings(_env_file=None, embed_revision="main")
    with pytest.raises(ValueError, match="RAG_EMBED_REVISION"):
        indexing_configuration(settings)


def test_missing_explicit_configuration_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_ENV_FILE", str(tmp_path / "missing.env"))
    with pytest.raises(ValueError, match="RAG_ENV_FILE"):
        Settings()
    # Test fixtures can intentionally opt out of all dotenv files.
    assert Settings(_env_file=None).answer_model == "qwen3:30b"
