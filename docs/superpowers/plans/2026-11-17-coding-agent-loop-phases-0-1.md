# Coding Agent Loop (Phases 0–1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an extractable `coding_agent` package with ports, JSONL events, budgets/cancel, SEARCH/REPLACE edits, and a ReAct loop that replaces the single-shot `daemon.agent_run` path while keeping the loom worker + worktree.

**Architecture:** New top-level `coding_agent/` package with zero `daemon` imports. `RunSession` owns budgets, cancel, policy, and tool dispatch; `PatternRunner` only steers phases. Daemon adapters: `WorktreeSandbox`, JSONL tail → WS, minimal `agent_runs` row, cancel flag. Worker still invokes Python `-m daemon.agent_run` but that module loads a manifest and runs the loop. Default locked strategy: ReAct. Pattern selection UX (spec phase 2+) is **out of this plan**.

**Tech Stack:** Python 3 / pytest, FastAPI daemon + aiosqlite, existing loom worker/worktree, urllib/OpenAI-compatible LLM client (reuse `daemon.llm_client` only from the daemon-side adapter / agent_run glue—not from `coding_agent` core).

**Spec:** `docs/superpowers/specs/2026-11-16-loom-coding-agent-pattern-routing-design.md` (phases 0–1 only)

**Follow-on plans (do not implement here):** Phase 2 selection UX; Phase 3 family pack; Phase 4+ verification/learning/overlays/extraction.

## Global Constraints

- `coding_agent` must not import `daemon` (enforce with a test)
- Do not rename or break existing `daemon/patterns.py` (knowledge PatternRepository — unrelated)
- Suggest/Accept and `loom-playbook.json` unchanged
- No mid-run pattern switch; strategy comes from manifest (hardcode ReAct for this plan)
- No `git push` from tools
- No invented cost/accuracy metrics
- Full suite: `PYTHONPATH=. .venv/bin/pytest tests/`
- Do not push / open / merge without explicit user approval
- Default budgets (pinned until settings UI): `step_limit=40`, `token_limit=100_000`, `cost_limit_usd=1.0`
- Shell allowlist v1: `pytest`, `python`, `python3`, `npm`, `npx`, `ruff`, `mypy`, `git` (subcommand gated separately)

## Review Focus

- `coding_agent` accidentally imports `daemon` → import-linter / AST test fails in CI → Task 1
- Path escape (`../` outside sandbox root) on read/edit → denied with structured error → Task 5
- Budget exhausted mid-loop → terminal JSONL `run.failed` / `stop_reason=budget_*`, no further LLM calls → Task 4 + 7
- Cancel flag appears between steps → `run.cancelled`, shell child terminated → Task 4 + 9
- Existing `tests/test_loom_agent_runner.py` argv still points at `daemon.agent_run` and settings key load still works → Task 8

## File map

| Path | Responsibility |
|------|----------------|
| `coding_agent/__init__.py` | Package marker |
| `coding_agent/ports.py` | `Sandbox`, `EventSink`, `UsageMeter`, `LlmPort`, `ContextSource` protocols |
| `coding_agent/events.py` | Event type literals + `JsonlEventSink` |
| `coding_agent/session.py` | `RunSession`, budgets, cancel poll, policy, tool dispatch |
| `coding_agent/tools/edit.py` | SEARCH/REPLACE apply (exact then bounded fuzzy) |
| `coding_agent/tools/fs.py` | `read_file`, `search` (rg) |
| `coding_agent/tools/shell.py` | Allowlist + approval-needed result |
| `coding_agent/tools/git_tools.py` | status/diff/log/add/commit (no push) |
| `coding_agent/tools/test_lint.py` | Run configured test/lint commands via sandbox |
| `coding_agent/patterns/schema.py` | Load/validate YAML; `schema_version` |
| `coding_agent/patterns/registry.py` | Registry + factory hooks |
| `coding_agent/patterns/families/react.yaml` | Active ReAct family |
| `coding_agent/patterns/families/*.yaml` | Other families as `status: planned` stubs (optional in this plan: at least one planned stub) |
| `coding_agent/runners/base.py` | `PatternRunner` protocol + turn result types |
| `coding_agent/runners/react.py` | ReAct runner |
| `coding_agent/selection/prefilter.py` | Pure helpers only (prefilter planned/capabilities)—used later; minimal stub OK |
| `daemon/coding_adapters.py` | `WorktreeSandbox`, LLM adapter wrapping existing client, context stub |
| `daemon/agent_run.py` | CLI: `--manifest` / `--run-dir`; build session; run ReAct |
| `daemon/runners.py` | Pass manifest path / run dir into argv when available |
| `daemon/registry.py` | `agent_runs` table + CRUD (minimal columns for phase 1) |
| `daemon/agent_runtime.py` / `api.py` | Create run dir + manifest on implement; cancel endpoint; JSONL tail → WS |
| `tests/test_coding_agent_*.py` | Package tests |
| `tests/test_agent_run_loop.py` | CLI/integration with fake LLM |

---

### Task 1: Package skeleton + ports + no-daemon-import guard

**Files:**
- Create: `coding_agent/__init__.py`, `coding_agent/ports.py`
- Test: `tests/test_coding_agent_imports.py`

**Interfaces:**
- Produces: Protocol classes `Sandbox`, `EventSink`, `UsageMeter`, `LlmPort`, `ContextSource` in `coding_agent/ports.py` (method names only as used by later tasks: `Sandbox.root() -> Path`, `Sandbox.read_text(rel: str) -> str`, `Sandbox.write_text(rel: str, content: str) -> None`, `Sandbox.run(argv: list[str], *, timeout_s: float | None = None) -> CompletedProc`, `EventSink.emit(event: dict) -> None`, `UsageMeter.add_tokens(input_n: int, output_n: int) -> None`, `UsageMeter.cost_usd() -> float`, `LlmPort.chat(messages: list[dict], *, model: str) -> LlmReply`, `ContextSource.pack() -> str`)

- [ ] **Step 1: Write failing test** `test_coding_agent_tree_does_not_import_daemon` that walks `coding_agent/**/*.py` AST imports and asserts no `daemon` module

- [ ] **Step 2: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_coding_agent_imports.py -v` — expect FAIL (package missing)

- [ ] **Step 3: Create package + empty/protocol `ports.py`**

- [ ] **Step 4: Run test** — PASS

- [ ] **Step 5: Commit** `feat(coding_agent): add package skeleton and ports protocols`

---

### Task 2: JsonlEventSink + FakeSandbox

**Files:**
- Create: `coding_agent/events.py`, `coding_agent/testing/fakes.py`
- Test: `tests/test_coding_agent_events.py`

**Interfaces:**
- Consumes: `EventSink`, `Sandbox` from Task 1
- Produces: `JsonlEventSink(path: Path)`, `FakeSandbox(root: Path)`, `CompletedProc(returncode: int, stdout: str, stderr: str)`

- [ ] **Step 1: Failing tests** — `test_jsonl_append_is_line_delimited_dicts`; `test_fake_sandbox_read_write_roundtrip`; `test_fake_sandbox_rejects_escape`

- [ ] **Step 2: Implement** sink + fake

- [ ] **Step 3: pytest** those tests — PASS

- [ ] **Step 4: Commit** `feat(coding_agent): JsonlEventSink and FakeSandbox`

---

### Task 3: Pattern schema loader + ReAct YAML (+ one planned stub)

**Files:**
- Create: `coding_agent/patterns/schema.py`, `coding_agent/patterns/registry.py`, `coding_agent/patterns/families/react.yaml`, `coding_agent/patterns/families/orchestrator_workers.yaml` (`status: planned`)
- Test: `tests/test_coding_agent_pattern_schema.py`

**Interfaces:**
- Produces: `load_patterns(dir: Path) -> PatternRegistry`, `PatternRegistry.get(id: str) -> PatternDoc`, `PatternRegistry.active_families() -> list[PatternDoc]`, `PatternDoc` fields per spec §4.3 including `schema_version: int` (start at `1`), `status: Literal["active","planned"]`
- `active_families()` excludes `planned`

- [ ] **Step 1: Failing tests** — valid react loads; planned excluded from `active_families`; missing `schema_version` raises; unknown field ignored or rejected (pick **reject unknown required-only**: require listed fields, ignore extras **or** reject extras—**pin: reject if `schema_version` missing; allow unknown keys with warning** for forward compat)

- [ ] **Step 2: Implement loader + YAML**

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(coding_agent): pattern schema loader and react family`

---

### Task 4: RunSession budgets + cancel

**Files:**
- Create: `coding_agent/session.py`
- Test: `tests/test_coding_agent_session.py`

**Interfaces:**
- Consumes: ports, `JsonlEventSink`
- Produces: `RunSession(manifest, sandbox, events, llm, meter, context)`, `RunSession.check_can_continue() -> None` (raises `BudgetExceeded` / `RunCancelled`), `RunSession.request_cancel() -> None`, `RunSession.poll_cancel_file() -> bool`, defaults `step_limit=40`, `token_limit=100_000`, `cost_limit_usd=1.0`

- [ ] **Step 1: Failing tests** — `test_step_budget_stops`; `test_cancel_flag_file_stops`; `test_token_budget_stops`

- [ ] **Step 2: Implement RunSession skeleton** (tool dispatch can be no-op stubs until Task 5–6)

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(coding_agent): RunSession budgets and cancel`

---

### Task 5: read + SEARCH/REPLACE edit + rg search

**Files:**
- Create: `coding_agent/tools/edit.py`, `coding_agent/tools/fs.py`
- Modify: `coding_agent/session.py` (register tools)
- Test: `tests/test_coding_agent_edit.py`, `tests/test_coding_agent_fs.py`

**Interfaces:**
- Produces: `apply_search_replace(path: Path, search: str, replace: str) -> ApplyResult` with `ok: bool`, `reason: str | None` (`not_found` | `multiple_matches` | `ambiguous_fuzzy` | None), fuzzy only when exact fails and unique fuzzy within bound
- Session tool names: `read_file`, `edit`, `search`

- [ ] **Step 1: Failing tests** — exact apply; not_found; multiple_matches; escape path denied; search returns capped lines

- [ ] **Step 2: Implement tools + wire into session dispatch**

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(coding_agent): read, search, and SEARCH/REPLACE edit tools`

---

### Task 6: shell allowlist, git (no push), test/lint tools

**Files:**
- Create: `coding_agent/tools/shell.py`, `coding_agent/tools/git_tools.py`, `coding_agent/tools/test_lint.py`
- Test: `tests/test_coding_agent_shell.py`

**Interfaces:**
- Produces: shell tool returns `need_approval=True` when argv[0] not in allowlist; `git push` always rejected; `run_tests` / `run_lint` call sandbox with configured commands from manifest

- [ ] **Step 1: Failing tests** — allowlisted `pytest` runs; `rm` needs approval; `git push` rejected

- [ ] **Step 2: Implement**

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(coding_agent): shell allowlist, git, test/lint tools`

---

### Task 7: PatternRunner protocol + ReAct runner

**Files:**
- Create: `coding_agent/runners/base.py`, `coding_agent/runners/react.py`
- Test: `tests/test_coding_agent_react_runner.py`

**Interfaces:**
- Consumes: `RunSession`, `LlmPort`
- Produces: `PatternRunner` protocol with `run(session: RunSession) -> RunOutcome`; `ReactRunner`; LLM tool-call or JSON-action protocol **pin: model returns a single JSON object** `{"thought": str, "tool": str | null, "args": object, "done": bool}` parsed from chat content (no provider-specific tool API required in phase 1)

- [ ] **Step 1: Failing test** — fake LLM scripted: think → edit → done; assert files changed + JSONL has `run.succeeded`

- [ ] **Step 2: Implement ReactRunner loop** calling `session.check_can_continue()` each turn

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(coding_agent): ReAct PatternRunner`

---

### Task 8: Evolve `daemon.agent_run` + runner argv for manifest/run_dir

**Files:**
- Modify: `daemon/agent_run.py`, `daemon/runners.py`, `daemon/coding_adapters.py` (create)
- Test: `tests/test_loom_agent_runner.py` (extend), `tests/test_agent_run_loop.py` (new)

**Interfaces:**
- Consumes: `ReactRunner`, `RunSession`, adapters
- Produces: CLI `python -m daemon.agent_run --manifest PATH` (`--prompt` kept for backward compat: wraps single-shot **or** writes ephemeral manifest with ReAct—**pin: `--manifest` required for loop; `--prompt` alone keeps legacy single-shot chat** so existing tests that only check argv still pass; add new argv builder path for implement)
- `RUNNERS["loom-agent"].build_argv` gains optional manifest: when supervisor passes run manifest env `LOOM_AGENT_MANIFEST`, argv uses `--manifest`

- [ ] **Step 1: Failing test** — with fake LLM + temp worktree + manifest, `main([...])` exits 0 and events.jsonl ends with succeeded

- [ ] **Step 2: Implement adapters + CLI branch**

- [ ] **Step 3: Run** `tests/test_agent_run_loop.py` + `tests/test_loom_agent_runner.py` — PASS

- [ ] **Step 4: Commit** `feat(agent_run): run coding_agent loop from manifest`

---

### Task 9: `agent_runs` row, run dir/manifest on implement, cancel + JSONL→WS

**Files:**
- Modify: `daemon/registry.py`, `daemon/models.py`, `daemon/agent_runtime.py`, `daemon/api.py`
- Test: `tests/test_agent_runs_registry.py`, extend `tests/test_agent_api.py`

**Interfaces:**
- Produces: table `agent_runs` with phase-1 columns: `id`, `task_id`, `project`, `family_id` (default `react`), `modifier_ids_json` (`[]`), `status`, `worktree_path`, `run_dir`, `step_limit`, `token_limit`, `cost_limit`, `steps_used`, `tokens_used`, `cost_used`, `stop_reason`, timestamps
- `POST .../implement` creates run dir, writes `manifest.json` (`family_id=react`, budgets, task prompt), sets `LOOM_AGENT_MANIFEST` for worker
- `POST .../runs/{run_id}/cancel` writes cancel file
- Background/tail: read new JSONL lines → emit WS event `agent:run_event` (name pinned)

- [ ] **Step 1: Failing tests** — implement creates `agent_runs` row + manifest file; cancel writes flag; (tail can be unit-tested by feeding sink file)

- [ ] **Step 2: Implement registry + runtime + API**

- [ ] **Step 3: pytest** targeted + full `tests/test_agent_api.py` — PASS

- [ ] **Step 4: Commit** `feat(daemon): agent_runs, manifest implement, cancel and JSONL events`

---

### Task 10: Regression gate

**Files:** none new

- [ ] **Step 1: Run** `PYTHONPATH=. .venv/bin/pytest tests/` — expect PASS (full suite)

- [ ] **Step 2: Fix any breakages** without expanding scope into phase 2

- [ ] **Step 3: Commit** only if fixes needed: `fix: keep suite green after coding_agent loop`

---

## Spec coverage (phases 0–1)

| Spec item | Task |
|-----------|------|
| `coding_agent` package + ports | 1–2 |
| JSONL EventSink | 2, 9 |
| schema_version + built-in YAML | 3 |
| RunSession budgets/cancel | 4, 9 |
| SEARCH/REPLACE + tools | 5–6 |
| ReAct runner | 7 |
| Worker + worktree, replace loop path | 8–9 |
| Suggest/playbook unchanged | (no task — verified by not touching) |
| Phase 2+ selection/families/SaaS | Explicitly deferred |

## Out of this plan

Two-stage selection UI, non-ReAct active runners, Jev run judges, Langfuse/OTel exporters, Docker sandbox, project pattern YAML, calibrated percentages, `agent_cost_report --benchmark` per pattern.
