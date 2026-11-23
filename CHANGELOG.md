# Changelog

All notable changes to Loom OS are documented in this file.

## [0.3.0-alpha.1] — 2026-11-16

First public alpha after `v0.2.0`. GitHub prerelease only (not published to PyPI).

### Highlights

- **Loom Agent + orchestration loop** — dashboard chat grounded in project graph memory; pluggable decision providers (Jev / Ollama / GLiClass); Accept / Dismiss / Implement suggestions that drive the Kanban worker path
- **`./run.sh`** — one-command local bring-up for daemon + dashboard
- **Cross-project federation** — org-wide read-only search (`/api/federated/*` + Federation tab)
- **`loom wire`** — zero-config MCP / `CLAUDE.md` / `AGENTS.md` / `.cursorrules` wiring
- **Hybrid search** — text + vector + graph traversal; MCP `hybrid_search`
- **Team mode** — optional `--auth-token` / `LOOM_AUTH_TOKEN` for write-protected setups
- **Docs refresh** — expanded README, USAGE, API, and MkDocs docs-site index

### Fixes in this alpha

- Implement dismisses pending suggestions and emits `task:suggestion` (no stale chip / 409 Accept)
- Dismiss rejects non-pending suggestions and refreshes the cost panel via WebSocket
- Implement workers honor dashboard BYOK over process `DEEPSEEK_API_KEY`
- Filter result cache keys include keep/drop thresholds

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.1
./run.sh --open
# or: pip install -e ".[dev]" && loom start
```

Companion packages (`loom-client`, `langchain-loom`, dashboard npm package) remain at their own `0.1.0` versions for this alpha.
