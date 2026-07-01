# CLI reference

The `loom` command (installed via `pip install loom-os`) is a single entry point with subcommands. Running `loom` with no subcommand, or with a flag as the first argument (e.g. `loom --port 8472`), is treated as shorthand for `loom start` — both forms work.

## `loom start` (aka `loom --port ...`)

Start the daemon (FastAPI + uvicorn).

```bash
loom --port 8472          # shorthand — inserts "start" automatically
loom start --port 8472    # explicit form
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind host |
| `--port` | `8472` | Bind port |
| `--reload` | off | Enable uvicorn auto-reload (dev) |
| `--log-level` | `info` | Log level |
| `--auth-token` | none | Enable team mode with token-based auth (optional; the base filesystem protocol needs no auth) |

## `loom init`

Bootstrap a project: creates the inbox directory and a starter `register.json` in one step.

```bash
loom init --project my-app --project-path .
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | required | Project identifier |
| `--project-path` | `.` | Path to the project |
| `--agent` | `claude-code` | Initial agent name |

## `loom register`

Register a coding agent with a project (writes `register.json` directly).

```bash
loom register --agent claude-code --project my-app --project-path /abs/path
```

| Flag | Default | Description |
|------|---------|-------------|
| `--agent` | required | Agent name (e.g. `claude-code`, `codex`, `hermes`) |
| `--project` | required | Project identifier |
| `--project-path` | required | Absolute path to the project directory |
| `--version` | `1.0` | Agent version |
| `--capabilities` | none | Comma-separated capabilities (e.g. `code-analysis,bug-finding`) |

## `loom unregister`

Prints instructions (curl command or dashboard link) for removing an agent — there is no dedicated inbox file type for unregistration; it goes through the API/dashboard.

```bash
loom unregister --agent claude-code --project my-app
```

## `loom detect-agents`

Lists coding agents detected on this machine and prints ready-to-run `loom register` commands for each one found.

```bash
loom detect-agents
```

## `loom worker`

Run a worker that executes **Running** tasks from the task board. Must be run from a separate terminal; `--project-path` must point to a git repository, since the worker executes tasks in an isolated git worktree (branch `loom/task-<id>`).

```bash
loom worker --project my-app --agent claude-code --project-path /abs/path
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | required | Project identifier |
| `--agent` | `claude-code` | Agent name |
| `--project-path` | required | Absolute path to the git project |
| `--base-url` | `http://127.0.0.1:8472` | Daemon base URL |
| `--model` | none | Claude model override (optional) |
| `--max-budget-usd` | `5.0` | Max USD to spend per task |
| `--poll` | `2.5` | Poll interval (seconds) |
| `--once` | off | Process a single task (requires `--task <id>`) and exit |
| `--task` | none | Task id to process when `--once` is set |

## `loom-mcp`

Starts the MCP server, exposing graph queries and finding ingestion over the Model Context Protocol so any MCP-aware agent can read from and write to Loom OS.

```bash
loom-mcp
```

## Testing commands (daemon dev)

Not `loom` subcommands, but part of the daemon dev workflow from the repo root:

```bash
pytest tests/ -v                        # full suite (pytest-asyncio, asyncio_mode=auto)
pytest tests/test_api.py -v             # one module
pytest tests/test_api.py::test_health   # one test
bash scripts/smoke-test.sh              # end-to-end: daemon + agent + API, needs .venv
```

## See also

- [Quickstart](../quickstart.md) — the 5-minute path using `loom --port 8472`.
- [Connect Claude Code](../guides/connect-claude-code.md) — `loom register` vs. writing `register.json` by hand vs. the `loom-client` SDK.
