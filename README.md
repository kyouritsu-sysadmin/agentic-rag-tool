# Kyoritsu RAG

Persistent FastAPI/SQLAlchemy/PostgreSQL backend, separate ingestion worker, and Next.js/assistant-ui frontend. The database owns documents, jobs, conversations, messages, runs and citations.

**Start with [the team handover guide](docs/HANDOFF.md)** for all installation, configuration, model provisioning, startup, safe tests and recovery commands.

- `backend/src/kyoritsu_backend/`: application, RAG providers/services, ORM and worker.
- `backend/migrations/`: explicit Alembic migrations.
- `backend/tests/` and `frontend/tests/`: unit, integration and browser acceptance.
- `backend/scripts/`: contracts, taxonomy maintenance and source-package generation.
- `frontend/src/`: auth/chat UI and FastAPI transport.
- `deploy/`: supported application deployment and example configuration.
- `docs/`: [architecture](docs/ARCHITECTURE.md), [structure](docs/PROJECT_STRUCTURE.md), [database](docs/DATABASE.md), [verification](docs/VERIFICATION.md), [handover tracker](docs/IMPLEMENTATION_PLAN.md), and [cleanup manifest](docs/CLEANUP_MANIFEST.md).

Existing models are retained: ruri embeddings, optional BGE reranking, Qwen answer generation and Qwen chunk summaries. Mock providers verify application flow without model downloads or Ollama. Real model quality and hardware acceptance belong to deployment verification.

Legacy code and private data/results have been archived outside the maintained source package. Local PostgreSQL configuration/volumes and current environment files are preserved. Use the handover packaging command to export source without local artifacts; a Git clone includes only committed files.
