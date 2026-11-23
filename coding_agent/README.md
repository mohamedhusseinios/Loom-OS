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

### macOS disk image (full stack)

Build a DMG that bundles daemon + coding agent + dashboard launcher:

```bash
bash scripts/packaging/macos/build-dmg.sh
# → dist/Loom-Coding-Agent-<version>.dmg
```

Open the DMG, drag **Loom Coding Agent** to Applications (or run it in place). The app uses the primary **Warp** Loom icon (`docs/branding/loom-icon-warp-512.png` → `AppIcon.icns`). First launch installs a local copy under `~/Library/Application Support/LoomCodingAgent`, creates a venv, installs Python deps, runs `npm install` in `dashboard/`, then starts `./run.sh --open`.

Requires network on first run (pip / npm). Later launches reuse the installed copy.

> **Note:** Double-clicking the `.app` uses a minimal macOS PATH (Terminal-only installs are invisible). The launcher adds Homebrew, nvm/fnm, Hermes Node, and your login-shell PATH automatically. If Node still isn’t found, install with `brew install node` or from [nodejs.org](https://nodejs.org/), then reopen the app.

---

## How to use

### Dashboard (normal path)

1. Start Loom: `./run.sh --open` (or the DMG app).
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
