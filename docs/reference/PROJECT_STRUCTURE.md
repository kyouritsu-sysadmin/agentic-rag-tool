# Project Structure Guide (Next.js + FastAPI)

Reference layout for new projects and for anyone (developer or AI agent) adding code
to an existing one. Derived from the kscribe repo: it keeps what works there and
fixes what does not.

## Layout

```
project-name/
├── README.md                      # what it is, how to run it (5-minute quickstart)
├── CLAUDE.md / AGENTS.md          # rules for AI agents (points to docs/)
├── .gitignore
├── .env.example                   # every required var, no real values
├── docker-compose.yaml            # local dev stack (committed, no secrets)
│
├── backend/                       # FastAPI
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .python-version
│   ├── Dockerfile
│   ├── gunicorn_config.py
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/              # descriptive names: add_is_admin_to_users.py, not "fixes.py"
│   ├── app/
│   │   ├── main.py                # app factory: middleware, routers, lifespan, /health only
│   │   ├── core/                  # cross-cutting: no business logic
│   │   │   ├── config.py          # pydantic-settings (tiered)
│   │   │   ├── logging.py
│   │   │   ├── security.py        # JWT, hashing, crypto
│   │   │   └── exceptions.py      # global exception handlers
│   │   ├── db/
│   │   │   ├── session.py         # engine, AsyncSessionMaker, get_db
│   │   │   ├── base.py            # Base, mixins (timestamps)
│   │   │   └── models/            # one file per domain
│   │   │       ├── user.py
│   │   │       └── session.py
│   │   ├── schemas/               # Pydantic request/response, one file per domain
│   │   │   ├── user.py
│   │   │   └── session.py
│   │   ├── api/
│   │   │   ├── deps.py            # CurrentUser, get_db, pagination deps
│   │   │   ├── routes/            # thin: validate → call service → return
│   │   │   │   ├── auth.py
│   │   │   │   ├── users.py
│   │   │   │   ├── sessions.py
│   │   │   │   └── admin.py
│   │   │   └── ws/                # websocket endpoints + connection manager
│   │   ├── services/              # business logic, testable without HTTP
│   │   │   ├── auth_service.py
│   │   │   ├── session_service.py
│   │   │   └── summary_service.py
│   │   ├── integrations/          # adapters for outside systems
│   │   │   ├── msal_teams.py
│   │   │   ├── email.py
│   │   │   └── pdf.py
│   │   ├── pipeline/              # domain-specific processing (ASR / VAD / LLM clients)
│   │   │   ├── asr/
│   │   │   ├── vad/
│   │   │   └── llm/
│   │   ├── admin/                 # sqladmin views + auth
│   │   └── utils/                 # small pure helpers (cursor, serialize)
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── fixtures/
│   │   ├── unit/                  # services, utils (no DB / network)
│   │   ├── integration/           # API + in-memory/test DB
│   │   └── e2e/                   # live streaming tests (marked, opt-in)
│   └── scripts/                   # seed_admin.py, one-off tools
│
├── frontend/                      # Next.js (App Router, src/)
│   ├── package.json
│   ├── package-lock.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── eslint.config.mjs
│   ├── postcss.config.mjs
│   ├── Dockerfile
│   ├── .env.example
│   ├── AGENTS.md
│   ├── public/                    # static assets, audio worklets
│   └── src/
│       ├── proxy.ts               # Next 16 replacement for middleware.ts (CSP, etc.)
│       ├── app/                   # ROUTES ONLY: page/layout/loading/error files
│       │   ├── layout.tsx
│       │   ├── globals.css
│       │   ├── manifest.ts
│       │   ├── (auth)/            # public pages
│       │   │   ├── login/page.tsx
│       │   │   ├── register/page.tsx
│       │   │   └── reset-password/page.tsx
│       │   └── (app)/             # authenticated pages
│       │       ├── layout.tsx     # auth guard + header
│       │       ├── dashboard/page.tsx
│       │       ├── history/page.tsx
│       │       ├── session/[id]/page.tsx
│       │       └── settings/page.tsx
│       ├── features/              # code owned by one feature
│       │   ├── auth/
│       │   │   ├── components/    # auth-form.tsx, auth-guard.tsx
│       │   │   └── api.ts
│       │   └── session/
│       │       ├── components/    # recording-view, completed-view, session-states
│       │       ├── hooks/         # use-recorder.ts
│       │       ├── api.ts
│       │       └── types.ts       # zod schemas + inferred types
│       ├── components/
│       │   ├── ui/                # shadcn primitives ONLY (button, card, input…)
│       │   └── layout/            # header, logo, theme/language toggles
│       ├── lib/                   # framework-agnostic helpers
│       │   ├── api-client.ts      # fetch wrapper, token refresh, ApiError
│       │   ├── config.ts
│       │   ├── format.ts
│       │   └── utils.ts
│       ├── store/                 # zustand stores (auth.ts)
│       └── i18n/
│           ├── provider.tsx
│           ├── server.ts
│           └── locales/           # en.ts, ja.ts
│
├── services/                      # separately deployed microservices
│   └── vad_service/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── models/
│       └── service/
│
├── proto/                         # single source of truth for gRPC contracts
│   └── vad/v1/vad_service.proto
│
├── deploy/                        # production infra (committed; secrets stay out)
│   ├── nginx/
│   ├── env/*.env.example
│   └── compose/                   # prod / test compose files
│
├── scripts/                       # repo-level: gen_proto.sh, etc.
│
└── docs/                          # all design docs live here, not at root
    ├── ARCHITECTURE.md
    ├── DATABASE.md
    ├── DEPLOYMENT.md
    ├── PROJECT_STRUCTURE.md
    └── adr/                       # decision records (short, dated)
```

## Rules

1. **Backend layering: `routes → services → db / integrations`.** Routes never call
   MSAL, PDF or LLM code directly. Services never import FastAPI's `Request`.
2. **Schemas and models stay separate.** Pydantic goes in `schemas/`, SQLAlchemy in
   `db/models/`, one file per domain on both sides.
3. **`main.py` is wiring only.** Middleware, routers, lifespan, health/readiness.
   Startup jobs (e.g. orphaned-session sweep) belong in a service.
4. **`frontend/src/app/` holds routes only.** Code used by a single feature lives in
   `features/<name>/`. Move it to `components/` or `lib/` only once two features use it.
5. **`components/ui/` is shadcn primitives only.** No API calls or business logic.
6. **One source per contract.** gRPC lives in `proto/`; generated code comes from
   `scripts/gen_proto.sh`. Frontend API types are zod schemas mirroring `backend/app/schemas/`.
7. **Nothing loose at the root.** Notes go in `docs/`, experiments in a gitignored
   `scratch/`. No `.bak` files, throwaway `.py` files or `unwanted/` folders.
8. **Tests, deploy and compose files are committed.** Only real secrets (`.env`) are ignored.
9. **Consistent API prefixes.** Every HTTP router mounts under `/api/...`.
10. **Descriptive migration names.** `alembic revision -m "add_is_active_to_users"`,
    never `fixes` or `updates`.

## Where kscribe differs today

Known gaps in this repo that the rules above address:

- `.gitignore` excludes `tests/`, `deploy/`, `docker-compose.yaml`, `TESTING/`,
  `postgresql/` and `scripts/*.py`, so a fresh clone has no tests or deploy config.
- `app/routers/sessions.py` imports MSAL, PDF, crypto and the LLM directly; there is
  no services layer.
- `crypto.py`, `cursor.py`, `pdf.py`, `msal_app.py`, `email_setup.py`, `serialize.py`
  sit flat in `app/` instead of `core/`, `integrations/` or `utils/`.
- API schemas live in `app/database/schema.py`, next to the DB code.
- Generated proto code is committed twice: `app/pipeline/vad/gen/` and
  `services/vad_service/service/vad/`.
- The admin router is mounted at `/app/v1/admin`; all others use `/api/...`.
- Several migrations are named `fixes`, `admin` or `config_added`.
- Root clutter: design `.md` files, `unwanted/`, `pp.py`, `zsxdkjcnz.py`, a `.bak`
  compose file, a root `package-lock.json`, and both `TESTING/` and `tests/`.
- `frontend/src/lib/` mixes the API client, a React hook (`use-recorder.ts`) and all types.

**Keep as-is:** tiered `config.py`, the `(app)` route group, `components/ui/`, `i18n/`,
`proxy.ts`, the separately deployed `services/vad_service` with `proto/`, and the
`alembic/` setup.
