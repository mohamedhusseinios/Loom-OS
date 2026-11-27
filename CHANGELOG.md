# Changelog

All notable changes to Loom OS are documented in this file.

## [0.3.0-alpha.8] — 2026-11-27

Eighth public alpha after `v0.3.0-alpha.7`. GitHub prerelease only (not published to PyPI). Ships the coding-agent run loop with pattern selection, custom OpenAI-compatible providers, pluggable Decision models, Coding Agent UX polish, and follow-on security hardening.

### Highlights

- **Coding agent loop** — ReAct PatternRunner with read/search/edit/shell/test tools, run budgets and cancel, JSONL event sink, and dashboard Implement flow with preview + strategy lock
- **Phase 2 pattern selection** — two-stage catalog scoring, autonomy settings, Implement pattern picker, and runner fallback when a non-ReAct family is chosen
- **Custom chat providers** — manage `openai_compatible` providers in Agent settings; chat/decision roles resolve from saved providers without leaking keys to keyless endpoints
- **Pluggable Decision model** — Jev (TypeSafe / OpenRouter) and GLiClass clients with filter/judgment settings, cost report, and usage telemetry
- **Coding Agent UX** — clearer handoff, sessions, and run context; fixes for new-chat draft flash, stale project metrics, and accidental mis-clicks
- **Security follow-ups** — closes remaining ponytail-audit holes in workers, path trust, and search; safer cancel/respawn and custom-provider edge cases
- **Usage surfaces** — project cost summary and suggestion usage on the dashboard

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.8
./run.sh --open
# or: pip install -e ".[dev,llm,crypto]" && loom start
```

**macOS app:** chat UI DMGs from `v0.3.0-alpha.6` still apply for the desktop shell; install this tag (or `pip install -e .`) for the daemon. New `0.3.0a8` DMG builds can follow when the desktop bundle is rebuilt.

## [0.3.0-alpha.7] — 2026-11-24

Seventh public alpha after `v0.3.0-alpha.6`. GitHub prerelease only (not published to PyPI). Hardens team-mode auth, Kanban task binding, worker execution leases, MCP/inbox path trust, and safer coding-agent runner defaults from the ponytail security audit.

### Highlights

- **Team auth covers all API reads** — when `LOOM_AUTH_TOKEN` is set, Bearer is required on `/api/*` except `/api/health`; token compare is constant-time; short-lived `POST /api/ws-ticket` for WebSocket connect
- **Task routes bound to project** — PATCH / progress / worker / diff / merge return 404 when `task_id` belongs to another project
- **Atomic execution leases** — `execution_owner` claim before supervisor spawn and in `loom worker`, so dashboard one-shot and polling workers cannot double-run the same card
- **MCP + inbox path trust** — project ids cannot traverse out of `~/.loom/inbox`; `register.json` must point at a real directory (keeps existing DB path on re-register)
- **Safer runners + spend guardrails** — sandbox-bypass CLI flags only with `LOOM_ALLOW_UNSAFE_RUNNERS=1`; non-Claude runners get `LOOM_STDOUT_TIMEOUT_S` wall clock; Kanban status transitions enforced
- **Credentials at rest** — `state.db` chmod `0600`; optional Fernet encryption of BYOK keys via `LOOM_CREDENTIALS_KEY` (or auth token) when `cryptography` is installed
- **Ops knobs** — `LOOM_CORS_ORIGINS` for remote dashboards; shared-context regen debounced; unknown-agent heartbeats no longer silently “processed”

### Install (from this tag)

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
git checkout v0.3.0-alpha.7
./run.sh --open
# or: pip install -e ".[dev,llm,crypto]" && loom start
```

**macOS app:** chat UI DMGs from `v0.3.0-alpha.6` still apply for the desktop shell; install this tag (or `pip install -e .`) for the hardened daemon. New `0.3.0a7` DMG builds can follow when the desktop bundle is rebuilt.

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
