# Development Guide

## Prerequisites

- Python 3.11+
- Node.js 20+
- [Graphify](https://github.com/nousresearch/graphify) installed (`pip install graphifyy`)

## Setup

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS

# Python daemon
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dashboard
cd dashboard && npm install
```

## Running

```bash
# Single command — starts daemon + dashboard, stops both on Ctrl+C
./run.sh
```

| What | Where |
|------|-------|
| Daemon | `http://127.0.0.1:8472` |
| Dashboard | `http://localhost:3000` |

Or start each manually:

```bash
# Terminal 1: daemon only
loom --port 8472

# Terminal 2: dashboard only
cd dashboard && npm run dev
```

### CLI Options

```
loom --help

  --host HOST           Bind host (default: 127.0.0.1)
  --port PORT           Bind port (default: 8472)
  --reload              Enable auto-reload (dev mode)
  --log-level LEVEL     Log level (default: info)
```

## Project Structure

```
agentic-os/
├── daemon/                       # Python package — the Loom daemon
│   ├── main.py                   # CLI entry point (`loom`), launches uvicorn
│   ├── api.py                    # FastAPI routes + WebSocket + app lifespan
│   ├── models.py                 # Pydantic schemas
│   ├── registry.py               # SQLite CRUD (aiosqlite)
│   ├── graph_engine.py           # Graphify CLI wrapper
│   ├── router.py                 # Inbox event dispatcher
│   ├── watcher.py                # watchdog inbox monitor
│   ├── worker.py                 # Task worker CLI
│   ├── worktree.py               # Git worktree management
│   └── ...                       # Additional modules (ingest, temporal, etc.)
├── dashboard/                    # Next.js 16 app
│   ├── app/[locale]/             # Locale-segmented routes (en, ar)
│   ├── components/               # Feature + UI components
│   ├── i18n/                     # next-intl config
│   ├── messages/                 # en.json, ar.json
│   ├── lib/                      # API client + WebSocket hook
│   └── proxy.ts                  # Locale middleware
├── tests/                        # pytest suite
├── scripts/
│   └── smoke-test.sh
├── docs/                         # Documentation
├── pyproject.toml
└── README.md
```

## Running Tests

```bash
source .venv/bin/activate

# All tests
pytest tests/ -v

# Specific module
pytest tests/test_api.py -v
pytest tests/test_registry.py -v
pytest tests/test_router.py -v
pytest tests/test_graph_engine.py -v
pytest tests/test_watcher.py -v
pytest tests/test_worker.py -v
pytest tests/test_tasks.py -v

# Single test
pytest tests/test_api.py::test_health
```

The suite uses `pytest-asyncio` with `asyncio_mode = auto`. API tests inject a temp-backed registry/graph engine into the `daemon.api` module globals and run with the lifespan suppressed (no watcher, no `~/.loom` writes) — see `tests/test_api.py`.

### Smoke Test

```bash
bash scripts/smoke-test.sh
```

Starts the daemon, registers a test agent, sends a heartbeat, checks API responses — then cleans up.

## Daemon Patterns

When contributing, follow these conventions:

- **Module-global singletons.** `api.py` holds `registry`, `graph_engine`, `router`, `watcher`, `connected_clients` as module-level globals. Route handlers read them directly.
- **Test mode detection.** `lifespan` checks `registry is not None` to detect test mode and skips the watcher/broadcast task. Inject temp-backed instances before constructing `TestClient`.
- **Graphify subprocess.** Invoked via `subprocess.run(["graphify", ...])` on a thread (`asyncio.to_thread`). Stats read from `<project_path>/graphify-out/graph.json`.
- **Idempotent task dispatch.** `create_task` uses `INSERT OR IGNORE`. Dual-write pattern (inbox file + registry row) ensures safety.
- **Error mapping.** Handlers raise `HTTPException` (404, 400, 409) — never return `(body, status)` tuples.

## Dashboard Development

```bash
cd dashboard

npm run dev      # dev server (hot reload)
npm run build    # production build
npm run lint     # eslint
```

> **Next.js 16 / React 19:** read the guide in `dashboard/node_modules/next/dist/docs/` before writing code — APIs differ from training data. Locale middleware is `proxy.ts`, not `middleware.ts`.

No Python linter is configured. Only the dashboard has `eslint` via `npm run lint`.

## MCP Server

A standalone MCP server is available as `loom-mcp`:

```bash
loom-mcp --help
```

See `daemon/mcp_server.py` for implementation details.
