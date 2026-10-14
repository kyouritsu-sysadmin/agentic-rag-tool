from pathlib import Path
import os
import re
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = (
    BACKEND_DIR if (BACKEND_DIR / "pyproject.toml").is_file() else Path("/etc/kyoritsu-rag")
)


class Credential(BaseModel):
    token: SecretStr
    subject: str = Field(min_length=1)
    companies: list[str] = Field(min_length=1)
    admin: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://localhost/kyoritsu")
    credentials: list[Credential] = []
    cors_origins: list[str] = ["http://localhost:3000"]
    storage_dir: Path = Path("storage")
    model_backend: str = "local"
    device: str = "cpu"
    embed_model: str = "cl-nagoya/ruri-v3-310m"
    embed_revision: str = "18b60fb8c2b9df296fb4212bb7d23ef94e579cd3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    enable_rerank: bool = False
    ollama_url: str = "http://localhost:11434"
    answer_model: str = "qwen3:30b"
    enable_summary: bool = True
    summary_model: str = "qcwind/qwen2.5-7B-instruct-Q4_K_M"
    summary_timeout: float = Field(default=60, gt=0)
    request_timeout: float = Field(default=60, gt=0)
    generation_timeout: float = Field(default=300, gt=0)
    max_model_queue: int = Field(default=8, ge=1)
    max_active_runs: int = Field(default=8, ge=1)
    max_upload_bytes: int = Field(default=25_000_000, ge=1)
    job_lease_seconds: int = Field(default=120, ge=10)
    max_job_attempts: int = Field(default=3, ge=1)
    parser_timeout: float = Field(default=300, gt=0)
    worker_retry_max_seconds: float = Field(default=30, gt=0)
    parser: str = "pypdf"
    allow_test_provider: bool = False

    def __init__(self, **values):
        # Never pick up an unrelated project's .env merely because cwd changed.
        if "_env_file" not in values:
            explicit = os.environ.get("RAG_ENV_FILE")
            config = Path(explicit).expanduser().resolve() if explicit else CONFIG_DIR / ".env"
            if explicit and not config.is_file():
                raise ValueError("RAG_ENV_FILE must identify an existing configuration file")
            values["_env_file"] = config
        selected = values["_env_file"]
        base = Path(selected).resolve().parent if selected else CONFIG_DIR
        super().__init__(**values)
        if not self.storage_dir.is_absolute():
            self.storage_dir = (base / self.storage_dir).resolve()

    def validate_model_revisions(self):
        """Check before indexing/inference, without blocking offline administration."""
        if self.model_backend == "test":
            return
        for name in ("embed_revision", "rerank_revision"):
            if name == "rerank_revision" and not self.enable_rerank:
                continue
            if not re.fullmatch(r"[0-9a-f]{40}", getattr(self, name)):
                raise ValueError(
                    f"RAG_{name.upper()} must be an immutable 40-character model commit; see docs/HANDOFF.md"
                )

    @model_validator(mode="after")
    def validate_backend(self):
        if self.model_backend not in {"local", "test"}:
            raise ValueError("model_backend must be local or test")
        if self.model_backend == "test" and not self.allow_test_provider:
            raise ValueError("Test models require explicit RAG_ALLOW_TEST_PROVIDER=true")
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("device must be cpu or cuda")
        if self.parser not in {"pypdf", "marker"}:
            raise ValueError("parser must be pypdf or marker")
        tokens = [c.token.get_secret_value() for c in self.credentials]
        if len(tokens) != len(set(tokens)) or any(len(t) < 24 for t in tokens):
            raise ValueError("Credential tokens must be unique and at least 24 characters")
        return self
