# Handover completion tracker

Current scope: deliver the existing application as a reproducible source handover, retaining current models and PostgreSQL design. New identity/product/provider features remain deferred by agreement. The earlier implementation history is preserved in `archives/pre-handoff-2026-10-14.tar.gz`; this file tracks the current handover rather than obsolete phase gates.

## Implemented fixes

- [x] H01 Restore configurable chunk summaries in the durable ingestion worker; persist summaries and preserve old active versions on provider failure.
- [x] H02 Use port 8005 for the supported CLI default.
- [x] H03 Load all saved-answer pages and discard stale thread-specific branch responses.
- [x] H04 Load backend configuration independently of cwd; support explicit `RAG_ENV_FILE`; anchor relative storage paths.
- [x] H05 Pin existing embedding/reranker revisions; snapshot submitted indexing settings; fail mismatched/unsnapshotted jobs explicitly.
- [x] H06 Require explicit opt-in, a dedicated test role and a test database name before destructive test fixtures.
- [x] H07 Add the OCR image build option and summary-provider host access to the worker.
- [x] H08 Run browser ingestion in a separate worker process with all model calls mocked.
- [x] H09 Preserve deterministic keyword generation in maintained tooling (122 equivalent entries).
- [x] H10 Archive and checksum-verify legacy code/private results/data before retiring active-layout copies; preserve database volumes/configuration and local secrets.
- [x] H11 Remove retired Next.js API routes; all persistence remains in FastAPI.
- [x] H12 Consolidate setup/configuration/operations into `docs/HANDOFF.md`.
- [x] H13 Add source-only packaging with per-file hashes; restrict to Git-tracked files and exclude configured private paths and local artifacts.

## Final verification

- [x] V01 Backend unit/integration regressions: 45 tests passed against disposable PostgreSQL after the core fixes.
- [x] V02 Frontend runtime regressions: 11 tests passed, including multi-page branch loading.
- [x] V03 Post-cleanup full browser acceptance and final static/build checks.
- [x] V04 Backend/frontend Docker image builds and isolated runtime smoke checks.
- [x] V05 Source package integrity and clean-extraction setup verification.
- [x] V06 Final self-review, verification record and package regeneration.
- [x] V07 Record reviewed application files and legacy retirements on branch `v1.0.1`, excluding the pre-existing PostgreSQL Compose change. Packaging itself does not commit.

## Receiving-team configuration and acceptance

- [ ] Provision model endpoints/weights and credentials using `HANDOFF.md`; validate real-model quality and hardware capacity.
- [ ] Supply deployment domains/TLS/CORS, backup retention and monitoring policies.
- [ ] Accept optional scanned-PDF OCR with representative documents if enabling it.

## Deferred features (not blockers for the agreed code handover)

- Non-Ollama production answer adapter, if still desired; provider/protocol is unspecified.
- Signup/password/SSO, invitations, user-management UI and session lifecycle.
- Document-management UI and enabled chat attachments.
- Multiple-provider/model selection.
- Importing retained historical documents/chats and resolving their ownership.
