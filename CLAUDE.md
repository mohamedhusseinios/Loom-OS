# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project identity

This is **Loom** — a unified agent memory fabric that weaves multiple AI coding agents into one shared, Graphify-powered knowledge graph per project. Agents talk to Loom **only through the filesystem** (drop files in an inbox); there is no SDK, API client, or auth. A Next.js dashboard is the control plane.

Naming drift to be aware of: the package/CLI/product is **`loom`** (`pyproject.toml`, the `loom` command, README title), but the repo directory and all design/plan docs are named **`agentic-os`** (e.g. `docs/superpowers/specs/2026-06-25-agentic-os-design.md`). They refer to the same project. The README also links to some `*-loom-*` doc paths that don't exist — the real files use the `agentic-os` prefix.

## Commands

Two independent processes. Run each from its own directory.

### Daemon (Python, port 8472)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

loom --port 8472                 # start daemon (uvicorn); --reload for dev, --host/--log-level available
pytest tests/ -v                 # full suite (pytest-asyncio, asyncio_mode=auto)
pytest tests/test_api.py -v      # one module
pytest tests/test_api.py::test_health   # one test
bash scripts/smoke-test.sh       # end-to-end: starts daemon, registers an agent, hits the API, cleans up (needs .venv)
```

No Python linter is wired into the project (no `ruff`/`flake8` config or dev dependency). Only the dashboard has a configured linter (`npm run lint`).

### Dashboard (Next.js, port 3000)
```bash
cd dashboard
npm install
npm run dev      # hot-reload dev server
npm run build    # production build
npm run lint     # eslint
```

Open http://localhost:3000. The daemon must be running for the dashboard to show data.

## Architecture

### Two-process split
- **Daemon** (`daemon/`): FastAPI + uvicorn on `127.0.0.1:8472`. REST + a single `/ws` WebSocket. CORS allows only `http://localhost:3000`.
- **Dashboard** (`dashboard/`): Next.js 16 App Router on `:3000`. Talks to the daemon over REST + WebSocket; `BASE_URL`/`WS_URL` are **hardcoded to `localhost:8472`** in `lib/api.ts` and `lib/use-websocket.tsx`.

### The filesystem protocol (core concept)
Agents never call an API. They write files into `~/.loom/inbox/<project>/`, and the daemon reacts:

| File | Effect |
|------|--------|
| `register.json` | Upserts agent + project, triggers an initial full graph build |
| `heartbeat.json` | Marks agent online (offline after ~5 min of silence) |
| `finding-*.md` | Markdown + YAML frontmatter; if it references code `files`, queues an incremental graph update |
| `decision-*.md` | Architecture decision record (indexed as a finding) |
| `task-*.json` | A dispatched task (see dispatch flow below) |

After processing, each file is moved to `inbox/<project>/.processed/`. Persistent state lives in `~/.loom/state.db` (SQLite) and `~/.loom/daemon.log`.

### Daemon module map & data flow
```
watcher.py   watchdog observer on ~/.loom/inbox (recursive). Extracts <project>
             from the path, marshals events onto the asyncio loop via
             run_coroutine_threadsafe.
   ↓ (project, filepath)
router.py    Router.handle_file dispatches by filename to _handle_* methods,
             then moves the file to .processed/. Emits WsEvents onto an
             asyncio.Queue. Rate-limits graph updates to 1 / 30s / project
             (MIN_UPDATE_INTERVAL).
   ↓
registry.py  AgentRegistry: aiosqlite over ~/.loom/state.db. Tables: agents,
             projects, tasks. CRUD + graph-stat persistence.
graph_engine.py  GraphEngine: build/update/query/stats/topology/communities/flows.
api.py       FastAPI routes (read module globals) + WebSocket fan-out.
models.py    All Pydantic schemas (inbox payloads, registry models, WS events).
```

`api.py`'s `_broadcast_events()` background task drains `router.events` and pushes each `WsEvent` to every connected WebSocket client.

## Daemon patterns & gotchas

- **Module-global singletons, not DI.** `api.py` holds `registry`, `graph_engine`, `router`, `watcher`, `connected_clients` as module-level globals; route handlers read them directly. Tests exploit this: they assign `api_module.registry = <temp-backed AgentRegistry>` etc. before constructing `TestClient`. The `lifespan` checks `registry is not None` to detect **test mode** and skips starting the watcher and broadcast task. Follow this pattern when adding tested routes — see `tests/test_api.py`.

- **Graphify is invoked as a CLI subprocess, not in-process** (the README is wrong here). `GraphEngine.__init__` does `import graphify` *only* to set the `available` flag; the actual work runs `subprocess.run(["graphify", ...])` on a thread (`asyncio.to_thread`). Stats/topology/communities/flows are read from `<project_path>/graphify-out/graph.json`. If that file is absent, endpoints return empty results rather than erroring.

- **Task dispatch is a dual-write with idempotency.** `POST /api/projects/{id}/dispatch` writes *both* the `task-*.json` inbox file *and* the registry row. `registry.create_task` uses `INSERT OR IGNORE` and returns whether a new row was created. So when the watcher later reprocesses the dropped file (`router._handle_task`), the duplicate insert is a no-op and the WS event is not re-emitted. Preserve this contract if you touch either path.

- **`upsert_project` vs `create_project`.** `upsert_project` uses `ON CONFLICT ... DO UPDATE` that deliberately does **not** reset graph-stat columns (re-registration keeps node/edge counts). `create_project` raises `ProjectExistsError`, which `api.py` maps to HTTP 409.

- **Error → status code mapping is explicit.** Handlers raise `HTTPException` (404 missing project, 400 bad input, 409 duplicate). Tests in `test_api.py` guard against regressions where handlers returned a `(body, status)` tuple (a Flask-ism) instead.

## Dashboard specifics

- **This is Next.js 16 + React 19 — read the bundled docs first.** `dashboard/AGENTS.md` (and `dashboard/CLAUDE.md`, which just `@`-imports it) warn that APIs/conventions differ from training data. **Before writing dashboard code, read the relevant guide in `dashboard/node_modules/next/dist/docs/`.**
  - Notably: the locale-negotiation middleware is **`proxy.ts`**, not `middleware.ts` (renamed in Next 16).

- **i18n via next-intl 4** with the locale in the URL path. Locales: `en` (default) and `ar` (RTL). Config: `i18n/routing.ts` (locales + `isRtl`), `i18n/request.ts` (message loading), `i18n/navigation.ts`. Translations live in `messages/{en,ar}.json`. All routed pages live under `app/[locale]/`; the root `app/layout.tsx` is minimal and `app/[locale]/layout.tsx` sets `<html lang dir>`, swaps fonts for RTL, and wraps children in `NextIntlClientProvider` + `WebSocketProvider`. Add UI strings to **both** locale files.

- **One shared WebSocket for the whole app.** `WebSocketProvider` (`lib/use-websocket.tsx`) opens a single `ws://localhost:8472/ws` connection and fans events out to subscribers keyed by event type (e.g. `agent:dispatched`) or `project:<id>`. Never open sockets per-component — call `useWebSocket()` and `subscribe(...)`. It throws if used outside the provider.

- **UI stack:** shadcn (v4, components in `components/ui/`), Tailwind v4, `@base-ui/react`, `lucide-react`, dark theme. Graph visualization uses `cytoscape` + `cytoscape-cose-bilkent` (`components/graph-canvas.tsx`, `graph-controls.tsx`, `node-detail.tsx`). Agent management: `agent-card`, `agent-wiring`, `dispatch-modal`, `dispatch-history`.

## Docs & roadmap

- Design specs: `docs/superpowers/specs/` (core design + dashboard-features design).
- Implementation plans: `docs/plans/` — including `2026-06-26-competitor-gap-closure-implementation.md` (active roadmap) with a supporting competitor analysis under `docs/reports/`.
- The top-level `README.md` is partly stale: its "Out of Scope (v1)" list (graph visualization, dashboard task dispatch, project CRUD) has **all been implemented**. Trust the code over the README for current capabilities.
