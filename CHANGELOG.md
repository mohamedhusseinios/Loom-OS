# Changelog

All notable changes to Loom OS are documented in this file.

## [0.3.0-alpha.2] — 2026-11-23

Second public alpha after `v0.3.0-alpha.1`. GitHub prerelease only (not published to PyPI). Includes the macOS **Loom Coding Agent** interim DMG.

### Highlights

- **Coding Agent loop** — extractable `coding_agent` package with ReAct tool loop (read / SEARCH-REPLACE edit / shell / git / test), budgets, cancel, and worktree sandbox; Implement runs via worker manifest + JSONL events
- **Pattern selection (Phase 2)** — two-stage DecisionClient shortlist at Implement; top-3 picker; Let-agent-decide / autonomy settings; non-ReAct families fall back to ReAct until Phase 3 runners
- **Multi-provider chat** — OpenAI- and Anthropic-style chat providers, model listing, and `chat_provider` selection in Agent settings
- **Custom OpenAI-compatible providers** — add/remove custom endpoints for chat; optional SystemOne-compatible use for decision filter/judgment; DeepSeek env keys never sent to keyless custom endpoints
- **macOS Coding Agent app** — interim DMG (`scripts/packaging/macos/build-dmg.sh`) bundles daemon + coding agent + dashboard launcher (Tauri shell planned next)

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.2
./run.sh --open
# or: pip install -e ".[dev,llm]" && loom start
```

**macOS app:** download `Loom-Coding-Agent-0.3.0a2.dmg` from this release, open it, and run **Loom Coding Agent** (first launch installs under `~/Library/Application Support/LoomCodingAgent`).

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
