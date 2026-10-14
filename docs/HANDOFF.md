# Team handover and setup

This is the authoritative setup and configuration guide. The codebase includes a persistent FastAPI/PostgreSQL backend, a separate ingestion worker, and a Next.js/assistant-ui frontend. Model inference and organization-specific configuration are provisioned by the receiving team. See `VERIFICATION.md` for measured checks, `ARCHITECTURE.md` for design, and `CLEANUP_MANIFEST.md` for archived material.

## Supported scope

Implemented: assigned-token authentication and company/owner isolation; document upload/replacement/reindex APIs; durable ingestion jobs; parsing, token-bounded chunking, summaries, embeddings, lexical/vector retrieval and optional reranking; persisted chats, streaming, citations, branching, cancellation, archive/restore/delete.

Deferred by agreement: replacing the answer provider, signup/password/SSO and user-management UI, document-management UI/chat attachments, multiple-model routing, and importing private legacy records. These are separate feature projects. The existing answer and summary adapters use Ollama; models can be mocked for integration tests. Conversation summarization is not implemented: the restored summary capability is **per document chunk**, and retrieval/answers continue using original chunk text.

## Requirements and installation

- Python 3.12 (root `.python-version`), uv, Node 24 and npm.
- PostgreSQL 16 with pgvector. Migrations require permission to create the vector extension.
- An Ollama endpoint for real answers and chunk summaries; sufficient CPU/RAM or separately provisioned inference hardware.
- Models/download access or a pre-provisioned model cache for real embeddings, optional reranking and OCR.

From the repository root:

```bash
uv sync --frozen --extra models
npm ci --prefix frontend
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
cp deploy/.env.example deploy/.env
```

Copy examples only on first setup; do not overwrite configured files. Dependencies and entry points live in `backend/pyproject.toml`; root `uv.lock` and `.venv/` are shared. Optional scanned-PDF support requires `uv sync --frozen --extra models --extra ocr`. Later syncs without extras remove optional dependencies; launch with `uv run --no-sync` after selecting extras.

## Configure once

### Backend and worker

Both read **`backend/.env` regardless of the launch directory** in a source checkout. An installed wheel defaults to `/etc/kyoritsu-rag/.env`. Set `RAG_ENV_FILE=/absolute/path/service.env` to select another existing file. Process environment variables override dotenv values. Relative `RAG_STORAGE_DIR` resolves against the selected configuration file's directory; use an absolute path for shared deployments. Tests explicitly disable dotenv loading.

Set these in the selected backend environment:

- `RAG_DATABASE_URL`: SQLAlchemy async URL, `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE`. URL-encode special password characters. Local supported Compose DB: `127.0.0.1:5544/rag`; within Compose: `db:5432/rag`. Match `POSTGRES_PASSWORD` in `deploy/.env`.
- `RAG_STORAGE_DIR`: retained uploaded source files. API and worker must see the same files at this path. Back it up with the DB.
- `RAG_CREDENTIALS`: one-line valid JSON array of `{token, subject, companies, admin}`. Generate a unique token per person with `openssl rand -hex 32`. Keep `subject` stable to preserve ownership. Use company names from `backend/src/kyoritsu_backend/rag/org.py`. Empty credentials deny protected requests. Admin status does not bypass company scope. Restart API after changing credentials.
- `RAG_CORS_ORIGINS`: JSON array of exact browser origins, e.g. `["http://localhost:3000"]`. Add the actual port if the frontend runs on 3001. `localhost` and `127.0.0.1` are different origins.
- `RAG_MODEL_BACKEND=local`: real providers. Production must not enable `RAG_ALLOW_TEST_PROVIDER`.
- `RAG_DEVICE=cpu`: default. The worker is CPU-only; the API may use CUDA after hardware validation. CPU worker and GPU API settings may differ only in device placement, not indexing semantics.
- `RAG_PARSER=pypdf`: text PDFs, Markdown and UTF-8 text. `marker` enables optional OCR; install OCR dependencies before selecting it.
- Capacity/timeouts: `RAG_MAX_UPLOAD_BYTES`, `RAG_MAX_MODEL_QUEUE`, `RAG_MAX_ACTIVE_RUNS`, `RAG_REQUEST_TIMEOUT`, `RAG_GENERATION_TIMEOUT`, `RAG_PARSER_TIMEOUT`, `RAG_JOB_LEASE_SECONDS`, `RAG_MAX_JOB_ATTEMPTS`, `RAG_WORKER_RETRY_MAX_SECONDS`. Defaults are defined in `core/settings.py`; examples show common settings.

### Existing models

Keep the supplied defaults unless intentionally changing the model contract:

- Embedding: `RAG_EMBED_MODEL=cl-nagoya/ruri-v3-310m`, `RAG_EMBED_REVISION=18b60fb8c2b9df296fb4212bb7d23ef94e579cd3`. The schema requires 768 dimensions.
- Optional reranker: `RAG_RERANK_MODEL=BAAI/bge-reranker-v2-m3`, `RAG_RERANK_REVISION=953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, `RAG_ENABLE_RERANK=false` by default.
- Answer: `RAG_ANSWER_MODEL=qwen3:30b`.
- Chunk summary: `RAG_SUMMARY_MODEL=qcwind/qwen2.5-7B-instruct-Q4_K_M`, `RAG_ENABLE_SUMMARY=true`, `RAG_SUMMARY_TIMEOUT=60`. Summary failures fail the ingestion job and preserve the old active version; they do not save invented fallback text. Explicitly disabling summaries stores null.
- `RAG_OLLAMA_URL`: common answer/summary endpoint, normally `http://localhost:11434` locally or `http://host.docker.internal:11434` in Compose. Provision both named models on that server. No silent external-provider fallback exists.

Embedding/reranker revisions were resolved from upstream metadata on 2026-10-14; pinning is reproducibility evidence, not a quality assessment. Floating revisions such as `main` are rejected before real indexing/inference. Existing installations using `main` must set the immutable revisions and reindex retained sources; old indexes are not silently relabeled.

Uploads capture an indexing configuration snapshot. Workers fail jobs whose settings differ from that snapshot. Correct the configuration and retry; jobs created before snapshots were implemented require a new upload/import key. Changes to model revision/parser/summary policy should use a new import key or reindex request. API and worker must use identical indexing settings. Existing completed versions and citations remain retained.

### Frontend

`frontend/.env.local` contains only public configuration:

```dotenv
NEXT_PUBLIC_BACKEND_URL=http://localhost:8005
```

This address must be reachable **from the user's browser**. Never use the container hostname `api` in browser configuration. Rebuild the frontend after changing this value. Never put tokens, DB URLs or passwords in `NEXT_PUBLIC_*` variables. Users enter an assigned token at sign-in; it is kept in the current tab's session storage.

## Start locally

Configure `deploy/.env` and `backend/.env`, then from root:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d db
uv run --no-sync alembic -c backend/alembic.ini upgrade head
uv run --no-sync uvicorn kyoritsu_backend.main:create_app --factory --workers 1 --host 127.0.0.1 --port 8005
```

In separate terminals from root:

```bash
RAG_DEVICE=cpu uv run --no-sync rag-worker
npm --prefix frontend run dev
```

Open the actual frontend port printed by Next.js. The default is 3000. `/health/live` confirms API liveness. `POST /v1/models/warmup` requires an administrator token and loads embedding/optional reranker weights. `/health/ready` checks API ownership, database, loaded retrieval models and the answer-model catalog; a ready API does not prove the separately running worker or summary model is healthy. Verify those with a small document upload. A cold embedding provider keeps readiness at 503 until warmup or first use.

## Container deployment

The original `postgresql/docker-compose.yaml` and its database mount are historical local configuration and are excluded from the source handover package. Do not operate those volumes as part of cleanup. The supported stack is `deploy/compose.yaml`, with separate DB/source/model volumes.

Create `backend/.env.compose` from the example and configure container addresses (`db:5432`, `host.docker.internal:11434`). Set `BACKEND_ENV_FILE=../backend/.env.compose` in `deploy/.env`; the path is relative to `deploy/compose.yaml`. Keep this separate from local configuration.

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d db
docker compose --env-file deploy/.env -f deploy/compose.yaml build
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile tools run --rm migrate
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d api worker frontend
```

For OCR, set `INSTALL_OCR=true` in `deploy/.env`, set `RAG_PARSER=marker` in the backend configuration, and rebuild API/worker images. Both services receive the host gateway mapping for model access. `PUBLIC_API_URL` is the browser-facing API URL baked into the frontend image. Exposed application ports bind to loopback; supply your organization's TLS reverse proxy for remote users, with unbuffered SSE and matching CORS/request-size limits.

Run exactly one API process per database. The advisory lock rejects additional owners. Worker jobs are durable; interrupted jobs recover after lease expiry. In-progress chat generation becomes interrupted on API restart and is not automatically resumed. Configure process supervision for local deployment and monitor worker logs/job failures. Model compute and timeout behavior require load testing on the receiving team's hardware.

## Import and verify a document

Use authenticated FastAPI `/docs` to submit `POST /v1/documents` with `file` and JSON `metadata`, for example:

```json
{"company":"共立電機製作所","dept":"営業部","year":2025,"month":1,"import_key":"handoff-smoke-001"}
```

Poll `GET /v1/jobs/{job_id}` until completed, then ask a question using that company/period. Check streamed answer, citation download, refresh/history and sign-out. Use a new `import_key` for changed input/configuration. Replacement uploads include the existing `document_id` and unchanged scope metadata. `POST /v1/documents/{id}/reindex?import_key=NEW_KEY` uses retained source bytes; successful publication changes the active version atomically. Failed jobs can be retried through `POST /v1/jobs/{id}/retry` within the attempt limit. Chat attachments remain disabled; ingestion uses the API.

`rag-admin --url http://localhost:8005 query "question"` and `rag-admin evaluate corpus.json --output results.json` use the same retrieval service. Set `RAG_ACCESS_TOKEN` in the process environment. Evaluation reports retrieval recall/precision/latency, not model answer quality. Keep private corpora/results outside the source package. `backend/scripts/build_keywords.py --output /path/keywords.json` preserves the legacy deterministic taxonomy generator; it does not modify runtime aliases automatically.

## Safe verification

```bash
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
.venv/bin/pytest backend/tests/unit -q
.venv/bin/python backend/scripts/export_contracts.py --check
npm --prefix frontend run test:unit
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

Full integration/browser tests require a **disposable** PostgreSQL database, role `rag_test`, and database name `rag_test` or `rag_test_<suffix>`. Use a separate instance/volume from the application. The test role must own its tables. Tests truncate application tables and terminate their own ownership session as part of recovery checks.

Set these only in the test terminal:

```bash
export RAG_TEST_DATABASE_URL='postgresql+asyncpg://rag_test:integration-only@127.0.0.1:15434/rag_test'
export RAG_DATABASE_URL="$RAG_TEST_DATABASE_URL"
export RAG_ALLOW_TEST_DATABASE_RESET=1
.venv/bin/alembic -c backend/alembic.ini upgrade head
.venv/bin/alembic -c backend/alembic.ini check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/pytest backend/tests -q
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8018 npm --prefix frontend run build
frontend/node_modules/.bin/playwright install chromium
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 frontend/node_modules/.bin/playwright test --config frontend/playwright.config.ts
unset RAG_TEST_DATABASE_URL RAG_DATABASE_URL RAG_ALLOW_TEST_DATABASE_RESET
npm --prefix frontend run build
```

Browser tests launch API 8018, frontend 3018 and a **separate worker process**, use real PostgreSQL/files/parser subprocesses, and mock embeddings, reranking, summaries and answers. Model HTTP calls are prohibited in the fixtures. Test outputs do not establish real-model quality. Do not reuse test-mode indexes in production; model-backend fingerprints separate them.

## Backup, recovery and troubleshooting

Stop writes and back up PostgreSQL (`pg_dump -Fc`) plus the complete source directory at the same recovery point. Record app manifest/commit, Alembic revision and model revisions. Restore both to an isolated environment, migrate explicitly, and verify counts, retrieval and old citation downloads before changing a live connection. No source garbage collection is enabled; old versions preserve citations. Unreferenced failed-upload blobs require reference-aware maintenance, not blanket storage deletion.

- Connection refused: check host/port and whether the intended PostgreSQL service is running. Supported local DB is 5544; 5434 is the preserved historical instance.
- Failed to fetch: check the browser API URL, API process, CORS origin and HTTP/HTTPS consistency.
- Credentials parsing error: use a single-line valid JSON array with no trailing commas. Never paste tokens in issue reports.
- Job configuration mismatch: restart API/worker with matching pinned indexing settings, then retry. Re-upload old unsnapshotted jobs with a new key.
- No results after changing model revision: reindex sources; existing vectors are intentionally excluded until compatible.
- OCR import error: install OCR extras locally or rebuild the Docker images with `INSTALL_OCR=true`.
- Summary failure: check worker logs, summary endpoint/model availability and timeout. Correct and retry; the previous document version remains active.
- `RAG_SUMMARY_TIMEOUT` caps the complete summary request, including a response that keeps sending small chunks; a timeout fails the indexing job rather than publishing a partial summary.
- Typecheck references deleted routes in `.next/dev/types`: stop the frontend dev server, run `cd frontend`, `rm -rf .next/dev/types`, then `npm run typecheck`. This regenerates current route types; restart with `npm run dev`.
- API ownership lost: restart the API after DB recovery. Do not start a second API against the same DB.

## Delivering the repository

Review and commit maintained source, lockfiles, migrations, tests, CI and documentation. Current Git working-tree changes are not automatically included in a clone. No commit is created by the packaging command:

```bash
.venv/bin/python backend/scripts/package_handoff.py
```

It requires a Git checkout and creates `dist/kyoritsu-rag-handoff.tar.gz` from Git-tracked files within the approved source roots. New files must be reviewed and added to Git before packaging; untracked local files are excluded. Modified tracked files use their working-tree contents. `HANDOFF_MANIFEST.json` records file hashes and the base Git commit; this is a working-tree snapshot, not a committed release.

The packager excludes the selected `RAG_ENV_FILE` (default `backend/.env`) and the resolved `RAG_STORAGE_DIR`, even when tracked. It uses the same configuration precedence and path resolution as the backend, and fails if that configuration cannot be loaded. Run it with the deployment's configuration overrides if private paths differ from the defaults. Environment files, common private-key formats, legacy archives, dependencies, builds, default runtime storage and old PostgreSQL configuration are also excluded. Review tracked source for accidentally committed private data and inspect the package before sharing; this is not a general secret scanner. The private recovery archive under `archives/` must not be sent as the code package.
