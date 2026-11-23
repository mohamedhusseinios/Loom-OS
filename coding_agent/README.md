# Loom Coding Agent

Extractable **think → tool → observe** loop used by Loom OS when you **Implement** a task. The package has no `daemon` imports; Loom adapters live under `daemon/` and call into this library.

| Piece | Role |
|-------|------|
| `coding_agent/` | Ports, ReAct runner, tools, pattern YAML, selection helpers |
| `daemon/agent_run.py` | Manifest-driven worker entry (`python -m daemon.agent_run`) |
| Dashboard → Implement | Pattern picker (or *Let agent decide*) → worktree → this loop |

Design: [coding agent + pattern routing](../docs/superpowers/specs/2026-11-16-loom-coding-agent-pattern-routing-design.md) · Phase 2 plan: [selection UX](../docs/superpowers/plans/2026-11-22-coding-agent-phase-2-selection-ux.md)

---

## Install

### With Loom OS (recommended)

The coding agent ships inside the `loom-os` package (`coding_agent*` in `pyproject.toml`).

```bash
# From the Loom OS repo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: pip install -e ".[llm]"
./run.sh --open                  # daemon :8472 + dashboard :3000
```

From PyPI (daemon + coding agent; dashboard still from this repo):

```bash
pip install "loom-os[llm]"
loom start
```

**Prerequisites:** Python 3.11+, Node.js 20+ (dashboard), Git 2.25+. Configure a BYOK chat model in the dashboard **Agent** settings (DeepSeek / OpenAI-compatible).

### Desktop app (Tauri) — primary ship path

The **Loom Coding Agent** desktop app (`desktop/`, Tauri 2) is the primary way to ship and run the full stack. One window with **Agent** and **Dashboard** tabs; no browser is opened. The app owns the local daemon (`:8472`) and Next.js dashboard (`:3000`) and stops them on quit (it attaches instead if both are already healthy).

```bash
cd desktop
npm install
npm run tauri build
```

`tauri build` stages the stack sources (`daemon/`, `coding_agent/`, `dashboard/`, `pyproject.toml`, `run.sh`, no venv / `node_modules`) into the bundle via `desktop/scripts/stage-payload.mjs`. Artifacts land under Cargo's target dir, `desktop/src-tauri/target/release/bundle/` by default:

| Host | Output |
|------|--------|
| macOS | `bundle/macos/Loom Coding Agent.app`, `bundle/dmg/Loom Coding Agent_<version>_<arch>.dmg` |
| Windows | NSIS installer under `bundle/nsis/` (run the same command on Windows) |
| Linux | AppImage / deb under `bundle/appimage/`, `bundle/deb/` (run the same command on Linux) |

Only the macOS build is produced and exercised in this repo's workflow; Windows/Linux need a build on those hosts.

First launch of a release build copies the bundled payload to `~/Library/Application Support/LoomCodingAgent/app` (Linux: `~/.local/share/LoomCodingAgent/app`, Windows: `%APPDATA%\LoomCodingAgent\app`), creates a venv, `pip install -e ".[llm]"`, runs `npm install` + `npm run build` in `dashboard/`, then starts the daemon and `next start`. Logs are in `LoomCodingAgent/logs/`. Later launches reuse the install; a new app version refreshes sources and keeps the venv / `node_modules`. Requires network on first run.

Development: `cd desktop && npm run tauri dev` runs against the repo checkout (`next dev`).

**Prerequisites:** Python 3.11+, Node.js 20+, Git, Rust toolchain (to build). Double-clicked `.app` bundles get a minimal PATH, so the app bootstraps Homebrew, nvm/fnm, Hermes Node and your login-shell PATH itself.

### macOS disk image (interim, secondary)

The older shell-launcher DMG is kept as a fallback; prefer the Tauri app above.

```bash
bash scripts/packaging/macos/build-dmg.sh
# → dist/Loom-Coding-Agent-<version>.dmg
```

It installs the same support-dir copy and starts `./run.sh --open` (opens your browser). Requires network on first run (pip / npm).

---

## How to use

### Dashboard (normal path)

1. Start Loom: `./run.sh --open` (or the desktop app).
2. Open a project, chat with **Loom Agent**, or create a Kanban task.
3. **Accept** a suggestion (or move a card to Ready), then **Implement**.
4. Pick a strategy (top patterns) or **Let agent decide**.
5. Watch the run stream; **Cancel** stops the loop. Done cards include a reviewable worktree diff.

Pattern families (ReAct, Plan-then-Execute, TDD, Debug, Review-only, …) live in `patterns/families/*.yaml`. Selection autonomy defaults are under Agent settings (`selection_autonomy_enabled`, `autonomy_min_fit`, `autonomy_require_margin`).

### Worker (CLI)

With the daemon up and a project registered:

```bash
loom worker \
  --project my-app \
  --agent loom-agent \
  --project-path /abs/path/to/repo \
  --max-budget-usd 5.0
```

Dragging a task to **Running** (or Implement) attaches this worker; it executes in `loom/task-<id>` worktrees.

### Manifest loop (low-level)

```bash
python -m daemon.agent_run --manifest /path/to/run-manifest.json
```

Manifest fields include `prompt`, `run_dir` / `events_path`, budgets, optional `test_command` / `lint_command`, pattern `family_id`, and `cancel_path`. Events append as JSONL for the daemon to tail over WebSocket.

### Library import

```python
from coding_agent.runners.react import ReactRunner
from coding_agent.session import RunSession
from coding_agent.patterns import PatternRegistry, load_patterns
```

Implement the ports in `coding_agent/ports.py` (`Sandbox`, `EventSink`, `UsageMeter`, LLM client, context source) for a non-Loom host. Loom’s adapters are in `daemon/coding_adapters.py`.

---

## Layout

```
coding_agent/
  runners/          # ReAct (and future pattern runners)
  tools/            # fs, edit, shell/git, test/lint
  patterns/         # YAML families + schema
  selection/        # fit / prefilter helpers (Phase 2)
  session.py        # budgets, cancel, usage
  ports.py          # host-facing protocols
  proc_run.py       # subprocess helper (scrubbed env, process groups)
```

---

## Develop / test

```bash
source .venv/bin/activate
pytest tests/test_coding_agent_*.py tests/test_proc_run.py tests/test_coding_adapters.py -q
```

Do not import `daemon` from inside `coding_agent/` — keep the package extractable.
