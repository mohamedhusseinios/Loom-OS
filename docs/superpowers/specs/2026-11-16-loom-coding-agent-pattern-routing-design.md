# Loom Coding Agent + Pattern Routing — Design

**Date:** 2026-11-16  
**Status:** Approved (written-spec review 2026-11-17)  
**Related:**
- `docs/superpowers/specs/2026-11-13-loom-agent-orchestration-loop-design.md`
- `docs/superpowers/plans/2026-11-14-pluggable-decision-model.md`
- Current implement path: loom worker worktree → `daemon/agent_run.py` (single chat completion, not a tool loop)

---

## 1. Summary

Evolve Loom Agent into two coordinated capabilities, delivered in one architecture with incremental phases:

**(A) Standalone coding agent** — a real think → tool → observe loop with step/token/cost budgets, cancel, SEARCH/REPLACE edits, sandbox ports, verification, and BYOK models. Loom is the first adapter; the core package does not import `daemon`.

**(B) Pattern routing** — a large declarative pattern library (families + stackable modifiers). At **Implement**, a two-stage DecisionClient pipeline shortlists and scores strategies; the user picks one or delegates. Patterns differ in **loop control**, not in which tools exist. Fit scores are suitability (High/Medium/Low), not calibrated success probability.

**Non-negotiable constraints**
- Local only for this workstream; do not push or merge unless explicitly asked.
- Each phase ships something working; existing test suite must keep passing.
- Do not invent cost/accuracy metrics; report only from benchmarks / eval harnesses.
- Suggest/Accept and `loom-playbook.json` behavior stay unchanged.
- Pattern locked at run start (no mid-task family switch in v1).
- SaaS concerns are seams only (`tenant_id`, encrypted secrets port, metering, queue)—YAGNI for product features.

---

## 2. Decisions (from brainstorming)

| Fork | Decision |
|------|----------|
| Spec scope | One architecture spec for A+B; first deep slice is a real tool loop under default ReAct |
| Pattern change mid-run | Lock at start (v1); no mid-task family switch |
| Pattern authorship v1 | Built-in YAML only; `schema_version` from day one |
| Authorship roadmap | Then plan C (project modifiers/overlays), then plan B (full project YAML families); marketplace later |
| Playbook | `loom-playbook.json` unchanged (Suggest catalog only; not a pattern source) |
| Run ownership | Single `RunSession` owns budgets, cancel, approvals, usage; `PatternRunner` is loop control only |
| Selection UX | Pattern pick at **Implement**; Suggest/Accept remain board actions |
| Launch runners | Active: ReAct, Plan-then-Execute, TDD, Debug, Review-only; others `planned` (not shortlisted) |
| Edit format | SEARCH/REPLACE primary; exact then bounded fuzzy; structured apply errors |
| Implement path | Keep loom worker + worktree; replace `agent_run` with full loop |
| Package shape | Extractable `coding_agent` package; ports only; Loom adapters in `daemon/` |
| Events | Append-only JSONL in run dir; daemon tails → WS |
| Selection engine | Approach 1: DecisionClient for Stage 1 and Stage 2 |
| Cancel / budgets | Dashboard cancel must stop the run; budgets enforced inside the loop |

---

## 3. Architecture

```
Dashboard
  Suggest / Accept  →  existing orchestration (unchanged)
  Implement         →  strategy picker (top 3 / Let agent decide)
  Cancel / stream   ←  WS (daemon tails JSONL)

Daemon (Loom adapters)
  two-stage selection via DecisionClient → persist agent_runs
  start loom worker in worktree
  tail {run_dir}/events.jsonl → WS
  cancel → flag file and/or signal → RunSession

Worker entrypoint → coding_agent package (no daemon imports)
  RunSession
       ├── PatternRunner (family + modifiers → loop phases)
       ├── Tools (read, edit, search, shell, git, test/lint)
       ├── Sandbox          ← WorktreeSandbox
       ├── EventSink        ← JsonlEventSink
       ├── ContextSource    ← HybridGraph + repo map
       ├── KeyStore / LLM   ← BYOK via LiteLLM-shaped port
       └── UsageMeter       ← local meter → cost report
```

### Ports (coding_agent)

| Port | Role |
|------|------|
| `Sandbox` | Workspace root, exec, path confinement; v1 = git worktree |
| `EventSink` | Append structured events (JSONL implementation) |
| `ContextSource` | Task text, repo map, graph hits (decisions/findings) |
| `TaskSource` | Task fields / status (Loom registry adapter) |
| `KeyStore` | Resolve provider credentials without embedding secrets in the package |
| `UsageMeter` | Token/cost accounting per run |
| `SuggestionSink` / event bus | Optional; WS projection stays in daemon via JSONL tail |

SaaS later = new adapters (Docker sandbox, Postgres task store, queue workers) behind the same ports—not a rewrite of `RunSession`.

### Component responsibilities

| Unit | Purpose | Depends on |
|------|---------|------------|
| `coding_agent.session.RunSession` | Budgets, cancel, approvals, policy, tool dispatch | Ports |
| `coding_agent.patterns` | Schema, loader, registry, factory | YAML files |
| `coding_agent.runners.*` | PatternRunner implementations | RunSession |
| `coding_agent.tools.*` | read / edit / rg / shell / git / test | Sandbox, policy |
| `coding_agent.selection` (optional) | Pure prefilter / shortlist / fit-level helpers | Pattern registry |
| `daemon` selection + adapters | Stage 1/2 DecisionClient calls, persist `agent_runs`, worktree, JSONL→WS, graph, settings | coding_agent ports + `DecisionClient` |
| Dashboard | Implement picker, fit levels, cancel, event stream | REST + WS |

**Selection placement (explicit):** `DecisionClient` stays in the daemon (existing providers). The daemon owns Stage 1/2 HTTP calls and persistence. `coding_agent` exposes the pattern registry plus **pure** helpers (prefilter, candidate generation, fit-level mapping) so the package never imports `daemon`. Optional `coding_agent.selection` module = those pure helpers only.

---

## 4. Pattern registry, schema, catalog

### 4.1 Storage and authorship

- **v1:** built-in files under `coding_agent/patterns/` (families and modifiers).
- Every document includes **`schema_version`** so later project overlays (C) and full project patterns (B) can load without breaking changes.
- Load policy: schema validation required; a single corrupt file is excluded with a clear log error (tests fail fast if any built-in file is invalid).
- User/project YAML: **out of scope until phase 6 (C) then 7 (B)**.

### 4.2 Concrete strategy

`strategy = family_id + ordered modifier_ids[]`  
Example: `plan_then_execute` + `test_first` + `human_checkpoint`.

### 4.3 Family document fields

| Field | Notes |
|-------|--------|
| `id`, `name` | Stable id; human name |
| `kind` | `family` |
| `schema_version` | Required |
| `version` | Content version (distinct from schema) |
| `status` | `active` \| `planned` (`planned` never shortlisted) |
| `description` | Short prose |
| `when_to_use` | Criteria list (also Stage 2 score keys) |
| `anti_criteria` | Hard/soft exclude signals |
| `steps` / `graph` | Declarative phases the runner interprets |
| `allowed_tools` | Subset of tool ids |
| `required_capabilities` | e.g. `tests`, `network`, `git_write` |
| `expected_cost_class` | Coarse band for UX (Low/Med/High)—not dollar claims |
| `expected_steps` | Optional band |
| `runner` | Built-in runner key (default: map `id` → factory) |

### 4.4 Modifier document fields

| Field | Notes |
|-------|--------|
| `kind` | `modifier` |
| `stackable` | Typically true |
| `effects` | Policy deltas applied on `RunSession` (checkpoint, test-before-edit, budget cap, diff-only, self-review, …) |

Modifiers do **not** fork family runners; they mutate a shared policy object.

### 4.5 Launch catalog

**Active runners (first coding-capable family pack):**

1. ReAct loop  
2. Plan-then-Execute  
3. TDD loop  
4. Debug loop (reproduce → isolate → fix → regression)  
5. Review-only (no write tools)

**Planned (registry present, `status: planned`, not shortlisted):**  
Single-shot, Research-first / Explore-then-act, Orchestrator-Workers, Parallel fan-out, Evaluator-Optimizer / Reflection, Spec-driven, Refactor-safe, Migration, Prototype/spike, Docs/explain.

**Launch modifiers (honored where sensible):** human checkpoint, self-review, test-first, budget cap, dry-run/diff-only.  
**Planned modifiers:** cross-model review, multi-sample + vote (until multi-model wiring exists).

### 4.6 PatternRunner protocol

Same style as `DecisionClient`:

- Protocol: prepare / run turn (or step) / terminal states (`finished` | `need_approval` | `failed` | `cancelled`)
- Registry + factory keyed by runner id
- Adding a pattern = add YAML (+ optional custom runner module only if control flow is not covered by a generic family runner)

---

## 5. Two-stage selection + Implement UX

### 5.1 Timing

Selection runs at **Implement** (before the worker loop starts). Suggest/Accept stay board-action suggestions only.

### 5.2 Stage 1 — task profile + prefilter

Using DecisionClient (choice/score questions), produce a task profile:

- type: bug | feature | refactor | migration | docs | research  
- size, risk, `has_tests`, repo familiarity  

Then prefilter patterns:

- exclude `planned`  
- exclude unmet `required_capabilities`  
- exclude matches on `anti_criteria`  
- build a small candidate set of concrete strategies (family + high-value modifiers), target shortlist **~5**

**Guards:** max patterns scored in Stage 2; if DecisionClient skipped/unsure → **fallback ReAct** (optionally + budget-cap); never block Implement solely because selection failed.

### 5.3 Stage 2 — score shortlist only

Judgment client scores only the shortlist against each pattern’s `when_to_use` / fit criteria and modifier applicability.

**Display rules**

- Show **rank + High / Medium / Low** fit—not percentages.  
- Percentages only after calibration against logged outcomes (explicit later phase).  
- Expected cost = `expected_cost_class` / steps band; refine with `scripts/agent_cost_report.py --benchmark` per pattern when data exists—do not invent numbers.

### 5.4 UX

- Top 3 strategies on the task chip / picker: name, fit level, expected cost band, **why** (matched criteria).  
- User picks one, or **Let agent decide**.  
- Autonomy: auto-pick when top fit ≥ threshold **and** margin over #2 ≥ X; else ask. Defaults in settings/code.  
- Persist selection, then start worker with locked strategy in the run manifest.

### 5.5 Learning loop (log now, tune offline)

Per run log: recommended vs chosen, user override, outcome (tests pass, accepted, reverted), cost, steps, duration.

Uses:

- Tune criteria/weights offline (no silent auto-writes in v1)  
- Calibrate fit → later % display  
- Few-shot similar past tasks via graph memory  
- Feed `agent_cost_report.py --benchmark` per pattern  

---

## 6. RunSession, tools, sandbox, verification

### 6.1 RunSession

Single owner of:

- Locked strategy  
- Step / token / cost budgets and usage  
- Cancel flag  
- Approval queue  
- Tool policy (family allowed_tools ∩ modifiers)  
- Paths: worktree, run_dir  

Every model/tool call goes through the session: meter → policy → sandbox → event.

### 6.2 Stop conditions (enforced in-loop)

- Max steps / tokens / cost (check **before** each call)  
- Cancel  
- Runner finished  
- Unrecoverable tool error after N repairs  
- Optional judge “complete”  

Terminal JSONL event always written (`run.succeeded` | `run.failed` | `run.cancelled`).

### 6.3 Cancel

Dashboard → daemon sets cancel (flag file under run_dir and/or process signal). Loop polls between steps; in-flight shell: terminate then kill. Emit `run.cancelled`.

### 6.4 Tools (v1)

| Tool | Behavior |
|------|----------|
| `read_file` | Paths under sandbox root only |
| `edit` | SEARCH/REPLACE; exact match then bounded fuzzy; structured failure reasons |
| `search` | ripgrep; capped output |
| `shell` | Allowlisted commands auto-run; risky → `need_approval` |
| `git` | status/diff/log/add/commit as policy allows; **no push** in this design |
| `test` / `lint` | From settings or detected project commands |

### 6.5 Sandbox

- Port: `Sandbox`  
- Local adapter (delivery phases 0–7): existing git worktree  
- Docker / hosted sandbox: later adapter at extraction (delivery phase 8)—same port  

### 6.6 Context

Repo map + task fields + `ContextSource` hybrid graph (decisions, findings). Summarization/compaction when history exceeds a token budget. Graph augments file tools; it does not replace them.

### 6.7 Verification

- Run test/lint after edits and at runner gates (e.g. TDD).  
- Failures return as observations; loop continues until stop conditions.  
- Optional Jev judges: task complete? edit safe? grounded?—**fit/suitability**, not success probability.  
- Review-only: write tools disabled.

### 6.8 Models and observability

- LLM via LiteLLM-shaped port (BYOK: DeepSeek, Claude, GPT, Ollama).  
- Primary audit trail: JSONL events (and optional later DB mirror).  
- Langfuse and/or OpenTelemetry: optional exporters of the same events; not required to ship phase 1.

---

## 7. Data model

### 7.1 Unchanged

- `task_suggestions` — board Suggest/Accept telemetry  
- `loom-playbook.json` — Suggest catalog only  
- Existing agent chat tables for Suggest chat  

### 7.2 New table: `agent_runs`

One row per Implement coding run:

| Group | Columns |
|-------|---------|
| Identity | `id`, `task_id`, `project`, `tenant_id` NULL (seam) |
| Strategy | `family_id`, `modifier_ids_json`, `pattern_versions_json`, `schema_version` |
| Selection | `recommended_json`, `chosen_source` (`user`\|`auto`\|`fallback_default`), `user_override`, `stage1_profile_json`, `fit_levels_json`, `selection_scores_json`, decision provider/model/skip fields |
| Runtime | `status` (`pending_selection`\|`running`\|`awaiting_approval`\|`succeeded`\|`failed`\|`cancelled`), `worktree_path`, `run_dir`, `pid` |
| Budgets | `step_limit`, `token_limit`, `cost_limit`, `steps_used`, `tokens_used`, `cost_used` |
| Outcomes | `tests_passed`, `lint_passed`, `accepted`, `reverted`, `stop_reason`, `duration_ms` |
| Timestamps | `created_at`, `started_at`, `finished_at`, `updated_at` |

### 7.3 Filesystem run dir

Under worktree or `~/.loom/runs/{run_id}/`:

- `events.jsonl` — source of truth for the stream  
- `manifest.json` — strategy, budgets, task stub  
- `cancel` — flag file  
- optional `approvals/`  

**v1:** daemon tails JSONL → WS; persist final summary onto `agent_runs`. Optional `agent_run_events` DB mirror is later.

### 7.4 Settings additions

Autonomy threshold + margin; default budgets; shell allowlist; optional test/lint commands; observability exporter off by default.

### 7.5 Migration / reporting

- No destructive migration of `task_suggestions`.  
- Extend `scripts/agent_cost_report.py` for runs + per-pattern `--benchmark`.  
- Selection-accuracy eval reads recommended vs chosen vs outcomes.

---

## 8. Phased delivery

| Phase | Ships |
|-------|--------|
| **0 — Seams** | `coding_agent` package skeleton, ports, JSONL EventSink, fake/Null Sandbox, schema + loader (`schema_version`), PatternRunner protocol + ReAct stub; Implement behavior unchanged |
| **1 — Real loop** | Worker invokes full loop; SEARCH/REPLACE; read/rg/shell/git/test; budgets + cancel; WorktreeSandbox; JSONL→WS; default strategy ReAct |
| **2 — Selection UX** | Two-stage selection at Implement; top 3; Let agent decide; autonomy; persist selection on `agent_runs`; fallback ReAct; High/Med/Low only |
| **3 — Family pack** | Plan-then-Execute, TDD, Debug, Review-only + launch modifiers |
| **4 — Verification + judge** | Stronger test/lint gates; optional Jev judges; cost report per-pattern benchmark |
| **5 — Learning read-path** | Offline reports, optional graph few-shots; no automatic weight writes |
| **6 — Overlay authorship** | Project-level modifiers/overlays (plan C); playbook still separate |
| **7 — Full project patterns** | Plan B project/user YAML families |
| **8 — Extraction** | Standalone FastAPI (+ Pydantic + SQLAlchemy/Alembic) service; Loom daemon as adapter; Docker sandbox option; queue/Postgres/tenant metering remain seams until SaaS is explicitly scoped |

---

## 9. Testing

| Layer | What |
|-------|------|
| PatternRunner contracts | Per runner + shared modifier/policy application (DecisionClient style) |
| Tools | SEARCH/REPLACE exact/fuzzy/errors; path escape denied; allowlist vs approval; budget stop; cancel between steps |
| Selection | Prefilter rules; Stage 2 only shortlist; skip → ReAct; autonomy threshold/margin; no % without calibration |
| Integration | Implement → manifest → worker → JSONL → WS; cancel ends run |
| Golden tasks | Per active pattern fixtures; metrics only from harness / cost report |
| Selection-accuracy eval | Labeled expected family (and modifiers); top-1/top-3 from eval only |
| Regression | Full existing suite must pass each phase |

---

## 10. Risks

| Risk | Mitigation |
|------|------------|
| Edit apply failures burn budget | SEARCH/REPLACE + structured repair observations |
| Large library hurts accuracy/cost | `planned` excluded; Stage 1 prefilter; max Stage 2 scores |
| Fit read as success probability | High/Med/Low copy; calibration gate for % |
| Loom coupling blocks extraction | No `daemon` imports in `coding_agent`; adapters only |
| Cancel leaves orphans | Flag file + terminate/kill + terminal event |
| Scope explosion | Phases 0→1→2 before family pack |
| Thin runners without evidence | No cost/accuracy claims outside benchmark |

---

## 11. Out of scope

- Mid-task pattern switching  
- Marketplace; project YAML families before phases 6–7  
- Changing Suggest/Accept or playbook semantics  
- SaaS product features (billing, real multi-tenant isolation beyond seams)  
- Agent `git push` / remote merge  
- Loading GLiClass/torch in-process; replacing the DecisionClient provider set  
- Showing calibrated percentages without outcome-backed calibration  
- Invented metrics  

---

## 12. Open defaults (implementation plan may fix numbers)

These are intentionally not claimed as measured truth:

- Autonomy: initial threshold/margin values (code defaults; tunable in settings; revisit after selection-accuracy eval)  
- Default step/token/cost budgets per cost class  
- Shell allowlist contents  
- Stage 2 max patterns scored (suggested starting point: 5)  

Any published cost or accuracy number must come from the golden-task benchmark or selection-accuracy eval.

---

## 13. Success criteria (design-level)

1. Implement can run a multi-step tool loop in a worktree with budgets and cancel.  
2. Events are recoverable from JSONL after crash; dashboard can stream and cancel.  
3. Pattern selection at Implement shows top 3 with fit level + why; fallback to ReAct is safe.  
4. `coding_agent` remains import-clean of `daemon` so extraction is an adapter swap.  
5. Existing tests remain green; new claims about quality come only from benchmarks.  
