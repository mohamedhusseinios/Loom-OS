# Changelog

All notable changes to Loom OS are documented in this file.

## [0.3.0-alpha.6] — 2026-11-24

Sixth public alpha after `v0.3.0-alpha.5`. GitHub prerelease only (not published to PyPI). Includes the macOS **Loom Coding Agent** DMGs with Agent chat Markdown rendering, font zoom, copy actions, and live SSE streaming.

### Highlights

- **Markdown chat bubbles** — GFM replies (headings, lists, tables, highlighted code) in user/assistant/thinking bubbles, session previews, and suggestion prose; link hrefs sanitized
- **Chat font zoom** — header A−/A+ plus Ctrl/Cmd ±/0 and Ctrl/Cmd+wheel; scale persists in `localStorage`
- **Copy actions** — copy message, thinking, and fenced code blocks with brief “Copied” feedback
- **Live token streaming** — `POST .../agent/chat/stream` (SSE) for project chat; task chat stays one-shot through the same path; dashboard updates the assistant bubble live and aborts on session change

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.6
./run.sh --open
# or: pip install -e ".[dev,llm]" && loom start
```

**macOS app:** download `Loom-Coding-Agent-0.3.0a6.dmg` or `Loom-Coding-Agent-Tauri-0.3.0a6-aarch64.dmg` from this release, open it, and run **Loom Coding Agent** (first launch installs under `~/Library/Application Support/LoomCodingAgent`).

## [0.3.0-alpha.5] — 2026-11-24

Fifth public alpha after `v0.3.0-alpha.4`. GitHub prerelease only (not published to PyPI). Includes the macOS **Loom Coding Agent** DMGs with Agent chat Thinking UI and session archive/delete.

### Highlights

- **Collapsible Thinking** — chain-of-thought stays in an optional Thinking panel; the reply is distilled separately so CoT is not dumped as the answer
- **Reasoning replay** — assistant `reasoning_content` is stored and replayed across turns (fixes Reflection Beam / R1-style HTTP 400 on follow-ups); empty-content turns distill a user-facing reply
- **Archive & delete sessions** — soft-archive Agent chat sessions (Active / Archived toggle) with hover actions; hard delete removes chat + messages after confirm

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.5
./run.sh --open
# or: pip install -e ".[dev,llm]" && loom start
```

**macOS app:** download `Loom-Coding-Agent-0.3.0a5.dmg` or `Loom-Coding-Agent-Tauri-0.3.0a5-aarch64.dmg` from this release, open it, and run **Loom Coding Agent** (first launch installs under `~/Library/Application Support/LoomCodingAgent`).

## [0.3.0-alpha.4] — 2026-11-23

Fourth public alpha after `v0.3.0-alpha.3`. GitHub prerelease only (not published to PyPI). Includes the macOS **Loom Coding Agent** DMGs with project-chat graph grounding.

### Highlights

- **Project chat uses graph memory** — Loom Agent project-level chat (no task selected) now retrieves via `hybrid_query`, injects `.loom/SHARED_CONTEXT.md`, and answers from shared graph context on the first message instead of claiming it has no project files
- **Clearer LLM HTTP errors** — provider error bodies are surfaced (credential-looking substrings stripped) when chat completions fail

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.4
./run.sh --open
# or: pip install -e ".[dev,llm]" && loom start
```

**macOS app:** download `Loom-Coding-Agent-0.3.0a4.dmg` or `Loom-Coding-Agent-Tauri-0.3.0a4-aarch64.dmg` from this release, open it, and run **Loom Coding Agent** (first launch installs under `~/Library/Application Support/LoomCodingAgent`).

## [0.3.0-alpha.3] — 2026-11-23

Third public alpha after `v0.3.0-alpha.2`. GitHub prerelease only (not published to PyPI). Includes the macOS **Loom Coding Agent** interim DMG with OpenRouter Jev.

### Highlights

- **Jev via OpenRouter** — Agent settings decision filter/judgment can use TypeSafe Jev through OpenRouter SystemOne (`openrouter_jev`) with an OpenRouter API key; no separate TypeSafe account required

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.3
./run.sh --open
# or: pip install -e ".[dev,llm]" && loom start
```

**macOS app:** download `Loom-Coding-Agent-0.3.0a3.dmg` from this release, open it, and run **Loom Coding Agent** (first launch installs under `~/Library/Application Support/LoomCodingAgent`).

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
