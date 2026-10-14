# Verification record — updated 2026-10-14

Implementation branch: `v1.0.1`. Changes remain in the working tree. Dated entries distinguish earlier implementation checks from subsequent local setup and simulation; no commit was created during this verification.

## Handover fixes, cleanup and final review — 2026-10-14

Current source status supersedes the historical checkpoints below. The reviewed handover is recorded on branch `v1.0.1`; the generated source archive includes a per-file hash manifest. The pre-existing local PostgreSQL Compose change is excluded from the handover commit.

- **45 backend tests passed** after the fixes and again after final test-isolation review. All model providers were mocked. Coverage includes persisted chunk summaries, summary-provider response validation/failure, replacement preservation, API/worker indexing mismatch and retry, stable configuration/storage paths, pinned revision validation and destructive-test guards.
- **13 Playwright tests passed**: two complete browser scenarios and 11 runtime/SSE tests, including pagination beyond 100 saved answers. Browser ingestion now runs in a separate worker process with real PostgreSQL, source files and parser subprocesses. Fixture model HTTP transports reject external calls.
- Backend lint/format, generated API contracts, TypeScript, frontend production build and maintained documentation links passed. Frontend lint has zero errors and one existing local-image warning in `attachment.tsx`.
- Default backend and frontend Docker images built successfully. Non-root runtime model-library imports passed without loading weights. Separate API/worker containers using a temporary source volume and disposable PostgreSQL completed upload → summary → index → chat → citation download; frontend container HTTP startup and removed-route 404 checks passed. Test containers and their source volume were removed.
- The OCR Docker image also built successfully. Marker converter/model-helper/output imports passed with Hugging Face/Transformers offline flags, without loading weights or processing documents. Real scanned-document OCR acceptance remains the receiving team's task.
- Clean source archive extraction installed frozen core/development dependencies. A fresh `rag_test_handoff` database was migrated; Alembic reported no schema drift; all 45 backend tests passed from that extracted checkout. Model libraries are separately verified in the Docker image. Offline installation initially lacked a cached Ruff wheel; normal frozen installation succeeded.
- Original modified PostgreSQL Compose file was compared byte-for-byte with its pre-cleanup archive copy. Application databases/volumes were not modified. Local embedding/reranker `main` aliases were replaced with immutable commits; model choices, DB connection and credentials were preserved. Existing indexes using `main` require explicit reindexing.
- Archived 323 files, verifying every archived file hash before removing only the manifest-listed paths. Private sources, old evaluation data/results, legacy code and retired routes are excluded from source packaging. Database configuration/volumes, current secrets and the thermal watchdog remain preserved. Details: [cleanup manifest](CLEANUP_MANIFEST.md).
- Restored the regular frontend build using its existing local API address after browser tests. Source packaging excludes runtime artifacts and was checked against the local configured secret values; no matches were found.

### Review findings resolved

The original CLI used port 8000; configuration depended on cwd; legacy chunk summaries were absent from ingestion; workers could publish indexes with different settings; branch selection stopped at 100 answers; destructive test fixtures had no disposable-target guard. These now have fixes and regression coverage.

The final review additionally corrected the worker's host gateway for summary calls, the Compose example's local DB-only setup path, unintended private dotenv reads in old tests, an ambiguous browser assertion matching a hidden branch option, and the retired-route expectation (now 404). The legacy keyword generator had a duplicate literal key; removing its shadowed entry preserves its 122-entry output.

No unresolved blocking code defect was identified in this review scope. This is not a claim of production model quality or exhaustive security/load testing. Real inference, OCR accuracy, hardware capacity, TLS/identity provisioning and operational acceptance remain deployment tasks. The agreed deferred product features remain listed in [the tracker](IMPLEMENTATION_PLAN.md). The source archive contains the reviewed application and excludes private recovery material. Actual Git commit identity is recorded by Git and in the package manifest.

### Historical verification entries

The entries below describe earlier stages; their retired-route, worker-layout and cleanup statements are historical, not the final layout.

## Mock-model application simulation — 2026-10-14

User scope: verify the application flow without Ollama and with model dependencies mocked. The production LLM replacement has not been selected; this simulation does not replace the existing production answer adapter.

**Result: 34 backend tests and 11 Playwright tests passed.** The browser suite includes two complete browser scenarios and nine runtime/SSE tests. No application defect was reproduced by these scenarios. A newly added test initially matched both the sign-in error and Next.js route announcer; scoping the assertion to the sign-in screen fixed that test selector.

### Real and simulated components

- Real: FastAPI routes/services, authentication and company/owner checks, PostgreSQL/pgvector, SQLAlchemy, Alembic, source files, parser subprocess, chunking, PostgreSQL full-text/vector queries, SSE, and the Next.js standalone frontend.
- Simulated: deterministic 768-dimensional embeddings, simple lexical/token-count fixtures, pass-through reranking, and a visibly labeled streamed `[TEST PROVIDER]` answer. These fixtures establish control/data flow, not model quality.
- Browser fixture explicitly enables reranking and supplies an unusable Ollama address. Its synchronous and asynchronous HTTPX network transports reject outbound HTTP. The new integration test additionally asserts zero attempted external HTTP requests while indexing, retrieving, reranking, and completing a cited answer.
- The browser fixture runs the real ingestion `process_one` workflow in a background task and invokes the real parser subprocess. It does not prove a separately deployed worker container/process supervisor works.
- Disposable PostgreSQL: `nw-rag-integration-20261013-b`, loopback port 15434, tmpfs storage. Browser fixture API: 8018; standalone frontend: 3018. Application databases on 5434 and 5544 and local user credentials were not changed by this simulation.

### Verified flows

- Invalid-token rejection, valid-token sign-in, model catalog, sign-out and absence of saved token after reload.
- Text upload through the API, duplicate-import handling, actual source storage, parser/chunk/index execution, completed job status, and authorized hybrid retrieval.
- New conversation, persisted submission, streamed mock answer, citations, refresh/history recovery, regeneration, cancellation and edited messages.
- Downloaded source bytes exactly match the uploaded fixture; saved branch selection updates the persisted thread head and displays its original conversation.
- Sidebar collapse/reopen, mobile drawer controls, Escape/focus return, archive, restore and deletion.
- Cross-user thread denial, cross-company source denial, idempotency conflicts, one-active-run admission and validation failures.
- Failed replacement preserves the previous active document; reindexing and expired-lease recovery preserve version/source integrity.
- Partial provider failure, parser timeout/cancellation, worker DB connection recovery, heartbeat failure, API ownership loss and orphan-run recovery.
- Backend lint/format, generated frontend contract consistency, TypeScript, frontend lint (one existing image-element warning), and production builds. Alembic reports no pending schema operations.

### Reproduce

Use only a disposable PostgreSQL database: the integration fixtures truncate application tables. Configure `RAG_TEST_DATABASE_URL` and `RAG_DATABASE_URL` to that same disposable database, then run from the repository root:

```bash
.venv/bin/alembic -c backend/alembic.ini upgrade head
.venv/bin/alembic -c backend/alembic.ini check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/pytest backend/tests -q
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8018 npm --prefix frontend run build
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 frontend/node_modules/.bin/playwright test --config frontend/playwright.config.ts
# Restore the normal local API address after the browser simulation:
npm --prefix frontend run build
```

The final build loads `frontend/.env.local`, currently configured for port 8005. Playwright stops its fixture servers when the suite finishes. The disposable database was stopped after verification.

### Not established by these checks

Real embedding/reranker relevance, LLM answer accuracy/latency, model-weight loading, GPU capacity, scanned-PDF OCR/table accuracy, production load/HA, deployment/container supervision and full user onboarding. Token sign-in remains the current implemented identity flow; there is no signup/password flow. The production answer adapter still requires replacement once the new provider/protocol is specified.

## Environment and provenance

- NW-RAG baseline: `994d527`; all 21 original tracked Python files passed an AST syntax check. Original Python implementations were preserved.
- UI source: K-RAG v2 `80f6de5bf772f25d50261c02da0925667291a997`, verified against the remote branch; only tracked `ui/` source was copied. The sibling checkout's modified requirements were untouched.
- Python 3.12.13; Node 24.15.0; uv 0.11.14. `uv.lock` and `package-lock.json` provide dependency resolution. Runtime checks used the explicitly enabled test model provider, not GPU models.
- Existing `rag_postgres/rag_database`: read-only inventory found an empty public application schema. No extension, table, migration or data mutation was made there.
- Integration database: disposable Timescale PostgreSQL 16.13 container on loopback port 15434, separate from the existing database on 5434. pgvector 0.8.2 enabled only in the test database.

## Verified checks

- Backend lint and formatting, original-source syntax, ORM metadata imports without model loading.
- Fresh Alembic baseline and reindex/reference migration; `alembic check` reports no pending schema operations.
- 33 backend tests (including review regressions and structural boundary checks): period parsing, full-width text, cross-year repeated months, omitted company, explicit overrides, authorization, validation, stable fusion, bounded long chunks, executor capacity under cancellation, conservative follow-ups, duplicate import, retrieval, persisted messages, idempotency conflicts, immutable source links, branches, cancellation, failed replacement, reindex, expired worker lease, partial provider failure, restart recovery and single-API ownership.
- Backup of test application data using `pg_dump -Fc`, restoration to a separate `rag_restore_test` database, and upgrade to `e5b4a40fb9f4`. Restored fixture counts: 2 chunks, 6 messages; zero orphan version references and zero incorrect vector dimensions. This validates the integrated schema upgrade path, not an unknown legacy schema migration.
- Frontend lint: no errors; two retained-reference warnings (`attachment.tsx` local image element, `tmp_type_check.ts` unused probe). TypeScript and Next.js production build passed.
- 10 Playwright tests: browser integration against the production frontend and real test API/database, runtime-action regressions, and SSE framing tests. The browser flow covers authorized upload/worker processing, model catalog, chat, source download, refresh, cancellation, UI edit/regenerate, branch selection and another user's access denial. Fragmented UTF-8/CRLF input and premature EOF are explicitly tested.
- New Compose configuration validates. Existing `postgresql/docker-compose.yaml` and its backup were preserved; its pre-existing trailing-blank-line warning is unrelated to these changes.

## Review defect regression evidence

- `backend/tests/unit/test_regressions.py`: chained/persisted follow-up scope, explicit overrides/topic resets, canonical metadata and invalid org relationships, complete oversized-row reconstruction with headers and token bounds, oversized-header rejection, real hung parser termination on timeout/cancellation, and retry-loop cancellation.
- `backend/tests/integration/test_application.py`: canonical and alias retrieval after upload, alias authorization denial, parser timeout followed by a completed job, heartbeat failure cancelling work before publication, worker recovery from a real refused database connection, context across long history/restart/branch selection, and actual PostgreSQL guard-session termination. The successor API starts; the old API returns 503 and cannot write stale run output.
- `frontend/tests/unit/runtime-actions.spec.ts`: actual runtime actions/store with controlled fetch responses, covering reconnect after stream and status-fetch failure, newer-snapshot/submission protection, overlapping initial sends, failed-creation retry, selection during creation, and independent reservations across two chats.
- No database schema change was needed; `alembic check` reports no new upgrade operations. The revised chunker is versioned in the import fingerprint and version provenance; reindexing uses a new import key, preserving older citation versions.
- Tests ran only against disposable PostgreSQL on port 15434. Existing PostgreSQL and legacy files were not modified. Runtime checks use the explicit test model provider, not production GPU/LLM/OCR inference.

## Structure refactor verification

- Backend factory reduced from 509 to 117 lines; HTTP routes, service workflows, database models, request/response schemas and serialization have explicit homes. Automated import checks enforce framework-independent application/database/provider layers and route delegation.
- Compared OpenAPI before/after: all HTTP paths, methods, parameters and response-status sets are preserved. Active JSON endpoints publish named response schemas; `export_contracts.py --check` confirms frontend wire types match.
- `alembic check` reports no new upgrade operations after the model split. The disposable database's tmpfs was reset when its container restarted; existing migrations recreated it before the passing integration run. No production database was used.
- All 33 backend tests pass. All 10 Playwright tests pass after moving source/tests; the 9 frontend unit tests also pass independently without fixture servers. The full browser flow covers sign-in, import/index, chat/source download, refresh, cancellation, edit/regeneration, branches and ownership denial.
- Frontend production build/type checks and lint pass (the same two retained-reference warnings remain). Backend lint/format, generated-contract drift checks, Compose validation and maintained documentation links pass.
- Framework configuration/public assets remain at frontend root. No running frontend source imports `frontend/legacy/`. Retired API endpoints continue returning 410, and deferred removal remains gated.
- No commit or deployment was performed. The source guide moved unchanged to `docs/reference/PROJECT_STRUCTURE.md`; the current layout and tracker are `docs/PROJECT_STRUCTURE.md` and `docs/IMPLEMENTATION_PLAN.md`.

## Targeted cleanup and uv migration verification

- User authorized the reviewed unused-code removals and pip-to-uv migration. The exact manifest is in the tracker (CLEAN-02, 03, 18, 22–25, 31–34). Only the empty placeholder and unused intent experiment were removed from the tracked legacy Python sources. Private data, historical evaluation results, database volumes, original Compose changes and backups remain untouched.
- Root `uv.lock` resolves 125 packages across extras/platforms; root `.venv` contains 124 installed distributions with API/dev/model/OCR dependencies under Python 3.12.13. `uv lock --check --offline`, `uv pip check` and repeat frozen sync dry-runs pass. Running uv from root or backend uses the same environment.
- PyTorch, Transformers model classes, Sudachi dictionary, Marker converter/model helpers and FastAPI import successfully without model-weight downloads. CUDA availability is true outside the sandbox (PyTorch CUDA runtime 13.0). This establishes installation/import readiness, not production model quality.
- Removed both superseded environments after verification; their package inventory and nonstandard tox file are retained under `docs/reference/`.
- All 33 backend tests pass in the new environment. Migrations and Alembic metadata checks pass against disposable PostgreSQL only. Backend lint/format and generated frontend contracts pass.
- Frontend strict unused-symbol/type checking, lint and production build pass; one existing image-element lint warning remains. All 10 Playwright tests pass using the standalone production server and root uv API environment.
- Repeating browser verification exposed a fixture assumption about an empty chat list and an edit-completion race. The test now starts a fresh thread and waits for the persisted edit run to complete; the complete suite passes with existing test chats present.
- Isolated standalone bundle starts without the source tree; page and 11 static assets return 200, and a retired route returns 410. Traced server dependencies occupy approximately 53 MB before static assets, compared with 807 MB for the development node_modules tree; these are directory sizes, not measured Docker image sizes.
- Compose validates with `--no-env-resolution` (real backend `.env` has not been provisioned). Dockerfiles and contexts were updated, but full image builds/deployment remain unverified.

## Release gates still open

- Real ruri/BGE/Ollama latency, GPU memory, accuracy and grounded-answer acceptance on an approved labeled corpus. Test-provider scores do not establish production quality.
- Pin and validate actual embedding/reranker model commits. OCR/Marker imports are verified; model-weight loading and scanned-document quality remain unverified.
- Identify whether retained legacy documents/chat records exist elsewhere. Their schema, source paths and `global-user` identity mapping must be verified before implementing/executing a data-specific import. Never guess from `sql.txt` or stamp a populated legacy DB.
- Container image builds, production volume ownership, TLS/reverse-proxy settings, organizational identity provisioning and backup retention require deployment acceptance. Compose services were not launched.
- Full outage/load tests and long-running operational acceptance remain open. API restart/orphan recovery, guard-session loss and worker connection-failure recovery are tested; production GPU/Ollama stress and full database-server restart under load are not.
- Broader legacy retirement remains gated after the targeted authorized cleanup above. Datasets, historical evaluation artifacts, backups and remaining original implementations were preserved.
