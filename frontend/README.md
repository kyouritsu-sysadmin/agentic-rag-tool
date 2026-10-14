# Kyoritsu chat frontend

Reused from `kyouritsu-sysadmin/K-RAG`, branch `v2`, commit `80f6de5bf772f25d50261c02da0925667291a997` (`ui/`). The sibling source repository was not modified. Its assistant-ui components, Markdown renderer, sidebar and external-store runtime remain the UI foundation.

FastAPI now owns every application record. `src/lib/api-client.ts` is the authenticated client, `src/lib/sse.ts` validates stream framing, `src/features/chat/actions.ts` handles acknowledged mutations and reconnects, and `src/features/chat/store.ts` is a reconciled cache. The previous Next.js persistence routes have been removed. The unused PostgreSQL adapter, `pg` dependencies, scratch probe and starter SVGs have been removed.

See the [root setup guide](../README.md), [handoff](../docs/HANDOFF.md) and [tracking file](../docs/IMPLEMENTATION_PLAN.md). No credentials or source data were copied from K-RAG.

Run `npm ci`, `npm run dev`, `npm run lint` or `npm run build`. Production `npm start` runs the standalone server; set `HOSTNAME`/`PORT` to change its bind address. Set `NEXT_PUBLIC_BACKEND_URL` before building. Model names come from the API. Per-tab sign-in uses an assigned bearer token; it never grants access merely by choosing a company. Chat attachment controls are disabled. Administrator document import is available through the authenticated FastAPI API.

Playwright tests use `playwright.config.ts` and require a migrated disposable PostgreSQL database in `RAG_TEST_DATABASE_URL`; see `docs/HANDOFF.md` for the test opt-in flag and exact build/test sequence.


Framework configuration remains at the frontend root; application source is under `src/`. Authentication UI/API lives in `features/auth/`; chat components, API calls, actions, state and view models live in `features/chat/`. `app/` contains page/layout/style composition only. Shared UI primitives belong to `components/ui/`; application provider composition lives in `components/layout/`.

Wire contracts in `src/lib/contracts/api.ts` are generated from backend request/response schemas. Regenerate from the repository root with `.venv/bin/python backend/scripts/export_contracts.py`. Feature view models convert ISO dates to `Date` and hold local UI state.

Run `npm run test:unit` for the fetch-controlled runtime/SSE tests without an API/database. `npm run typecheck` checks TypeScript. The full `npm test` also starts the browser fixture servers and needs the migrated disposable database as described above.

Docker runs the traced `.next/standalone/server.js` bundle plus `.next/static`, without copying source, tests or the full development dependency tree. The postbuild script copies static assets and any future `public/` files into that bundle.
