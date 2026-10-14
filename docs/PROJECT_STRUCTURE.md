# Current project structure

Active application code lives in `backend/` and `frontend/`. The installable Python package, PostgreSQL schema, API URLs, worker/CLI entry points, and frontend behavior are preserved by this reorganization.

```text
NW-RAG/
├── README.md
├── pyproject.toml, uv.lock, .python-version  # shared uv workspace and root .venv
├── .gitignore
├── .github/workflows/application.yml
├── backend/
│   ├── pyproject.toml, Dockerfile, Dockerfile.dockerignore, .env.example
│   ├── alembic.ini
│   ├── migrations/versions/
│   ├── scripts/                     # contracts, keywords, handover packaging
│   ├── src/kyoritsu_backend/
│   │   ├── main.py                   # factory, lifespan, health, assembly
│   │   ├── api/
│   │   │   ├── deps.py, exceptions.py
│   │   │   └── routes/               # auth, models, retrieval, threads, runs, documents, jobs
│   │   ├── schemas/                  # request/response contracts by domain + serialization
│   │   ├── core/                     # settings, identity, errors, logging, ownership, limits
│   │   ├── db/
│   │   │   ├── base.py, session.py, repositories.py
│   │   │   └── models/               # chat, documents, ingestion
│   │   ├── services/                 # workflows, catalog, startup recovery
│   │   ├── providers/                # models, answers, summaries, source-file adapters
│   │   ├── rag/                      # planning, taxonomy, fusion, chunking, indexing contract
│   │   ├── workers/                  # durable ingestion and isolated parsing
│   │   └── cli/
│   └── tests/
│       ├── support.py, database_safety.py
│       ├── unit/                    # no PostgreSQL required
│       ├── integration/             # API/PostgreSQL tests + conftest.py
│       └── e2e/                         # isolated API and independent worker fixtures
├── frontend/
│   ├── package.json, package-lock.json, Dockerfile, .env.example
│   ├── next.config.ts, tsconfig.json, components.json, eslint.config.mjs
│   ├── playwright.config.ts, playwright.unit.config.ts
│   ├── AGENTS.md, CLAUDE.md
│   ├── src/
│   │   ├── app/                     # page/layout/styles/metadata
│   │   ├── features/
│   │   │   ├── auth/                # API, sign-in gate and sign-out UI
│   │   │   └── chat/                # components, runtime provider, actions, API, store, view types
│   │   ├── components/
│   │   │   ├── ui/                  # reusable presentation primitives
│   │   │   └── layout/              # cross-feature provider composition
│   │   └── lib/
│   │       ├── api-client.ts, config.ts, sse.ts, utils.ts
│   │       └── contracts/api.ts     # generated from backend OpenAPI; do not hand-edit
│   └── tests/{unit,e2e}/
├── deploy/compose.yaml, .env.example
└── docs/
    ├── PROJECT_STRUCTURE.md, ARCHITECTURE.md, DATABASE.md, DEPLOYMENT.md
    ├── HANDOFF.md, IMPLEMENTATION_PLAN.md, VERIFICATION.md, LEGACY.md, ENVIRONMENT.md
    └── reference/                     # supplied structure guide and old environment inventory
```

## Boundaries

1. Routes validate/translate HTTP and call services; they do not query SQLAlchemy or invoke provider internals.
2. Services, repositories, RAG code, and providers do not import FastAPI/Starlette. Shared application errors are translated at the API boundary.
3. SQLAlchemy models and Pydantic contracts remain separate. All mapped domains share one declarative base and existing migrations.
4. Feature-specific React code and state stay inside the owning feature. `src/app/` composes routes; `components/ui/` contains presentation primitives, not API calls.
5. Backend JSON responses publish explicit schemas. Frontend wire types are generated from those schemas; feature view models handle browser-specific normalization.
6. `tests/unit/` can run independently. Database tests require an explicitly supplied disposable migrated database; browser tests start their own fixture servers.
7. Configuration, public assets, and environment files stay at their framework roots. Next.js aliases and shadcn paths point into `src/`.
8. Targeted unused-code cleanup is recorded in the tracker. Legacy code/private artifacts were archived before retirement; see CLEANUP_MANIFEST.md. Database volumes and local configuration remain protected.

## Developer checks

Run these from the repository root:

```bash
.venv/bin/pytest backend/tests/unit -q
.venv/bin/python backend/scripts/                     # contracts, keywords, handover packaging --check
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
npm --prefix frontend run test:unit
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

See HANDOFF.md for all setup/configuration and integration/browser commands. The supplied reference guide is preserved in `docs/reference/PROJECT_STRUCTURE.md`; framework naming differences such as `src/kyoritsu_backend` and `migrations/` are intentional.
