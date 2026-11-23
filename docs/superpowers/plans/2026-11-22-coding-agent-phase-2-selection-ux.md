# Coding Agent Phase 2 — Selection UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At Implement, run two-stage pattern selection, show a top-3 picker (High/Med/Low + why), support Let-agent-decide / autonomy, persist the choice on `agent_runs`, and start the worker with a locked strategy — falling back to ReAct whenever selection fails.

**Architecture:** Pure helpers live in `coding_agent/selection/` (no `daemon` imports). Daemon module `pattern_selection.py` calls existing `DecisionClient` filter+judge roles with a pattern pack, then `AgentRuntime` opens the coding run with the locked strategy. Dashboard opens an Implement picker before spawn unless autonomy auto-picks. Phase 3 runners are out of scope: non-`react` families may be shortlisted for UX/learning, but the worker executes `ReactRunner` with `runner_fallback=true` until Phase 3.

**Tech Stack:** Python 3 / pytest, existing `DecisionClient`, FastAPI + aiosqlite, Next.js 16 dashboard + next-intl (`en`/`ar`).

**Spec:** `docs/superpowers/specs/2026-11-16-loom-coding-agent-pattern-routing-design.md` (§5 Selection UX, §7.2 selection columns, §8 Phase 2, §12 open defaults)

**Predecessor:** `docs/superpowers/plans/2026-11-17-coding-agent-loop-phases-0-1.md` (shipped on `cursor/coding-agent-loop-phases-0-1`)

## Global Constraints

- `coding_agent` must not import `daemon` (existing import AST test must stay green)
- Suggest/Accept and `loom-playbook.json` unchanged
- No mid-run pattern switch; strategy locked in `manifest.json` before worker start
- Fit display: High / Medium / Low only — never invent percentages
- DecisionClient skip/unsure → fallback ReAct; never block Implement solely because selection failed
- Only `ReactRunner` executes in this phase; other selected family ids persist + set `runner_fallback`
- Full suite: `PYTHONPATH=. .venv/bin/pytest tests/`; dashboard `npm run lint` after UI tasks
- Do not push / open / merge without explicit user approval
- i18n: every new UI string in both `messages/en.json` and `messages/ar.json`
- Pinned defaults (§12): `STAGE2_MAX=5`; `autonomy_min_fit="High"`; auto-pick only when top fit is High **and** #2 fit is strictly lower (or absent); `selection_autonomy_enabled=true`

## Review Focus

- DecisionClient skipped → Implement still starts with `family_id=react`, `chosen_source=fallback_default`, no 5xx → Task 5 + 6
- `planned` family never appears in preview shortlist even if YAML exists → Task 1 + 2
- Autonomy off or margin missing → preview returns `auto_decidable=false`; Implement with `choice=auto` returns 409 + recommendations (does not spawn) → Task 5 + 6
- User override of recommended family persists `user_override=true`, `chosen_source=user` → Task 3 + 6
- `coding_agent/selection/**` never imports `daemon` → Task 1 (covered by existing import guard)

## File map

| Path | Responsibility |
|------|----------------|
| `coding_agent/selection/__init__.py` | Package exports |
| `coding_agent/selection/types.py` | `FitLevel`, `TaskProfile`, `StrategyCandidate`, `RankedStrategy`, `AutonomyDecision` |
| `coding_agent/selection/prefilter.py` | Exclude planned / unmet caps / anti_criteria; build ~5 candidates |
| `coding_agent/selection/fit.py` | Score→FitLevel; rank; autonomy decidable? |
| `coding_agent/patterns/families/plan_then_execute.yaml` | Active catalog family (selection metadata) |
| `coding_agent/patterns/families/tdd.yaml` | Active catalog family |
| `coding_agent/patterns/families/debug.yaml` | Active catalog family |
| `coding_agent/patterns/families/review_only.yaml` | Active catalog family |
| `daemon/pattern_selection.py` | Stage 1/2 via DecisionClient; assemble preview DTO |
| `daemon/registry.py` / `daemon/models.py` | Selection columns on `agent_runs` + autonomy settings |
| `daemon/agent_runtime.py` | `preview_implement` + `implement(..., choice)` lock strategy |
| `daemon/api.py` | `POST .../implement/preview`, body on `POST .../implement` |
| `daemon/agent_run.py` | Read `family_id`; ReactRunner + optional `runner_fallback` event |
| `dashboard/components/implement-picker-modal.tsx` | Top-3 + Let agent decide |
| `dashboard/components/task-detail-drawer.tsx` / `suggestion-chip.tsx` | Open picker / autonomy path |
| `dashboard/components/agent-settings-panel.tsx` | Autonomy toggles |
| `dashboard/lib/api.ts`, `messages/{en,ar}.json` | Types + i18n |
| `tests/test_coding_agent_selection.py` | Pure selection helpers |
| `tests/test_pattern_selection.py` | Daemon Stage 1/2 + fallback |
| `tests/test_agent_runs_registry.py` | Selection column CRUD |
| `tests/test_agent_api.py` | Preview + implement body integration |
| `tests/test_implement_picker*` / lint | Dashboard coverage as practical |

---

### Task 1: Pure selection helpers

**Files:**
- Create: `coding_agent/selection/__init__.py`, `types.py`, `prefilter.py`, `fit.py`
- Test: `tests/test_coding_agent_selection.py`

**Interfaces:**
- Produces:
  - `FitLevel = Literal["High", "Medium", "Low"]`
  - `TaskProfile(type: str, size: str, risk: str, has_tests: bool, repo_familiarity: str)`
  - `StrategyCandidate(family_id: str, modifier_ids: list[str], doc: PatternDoc)`
  - `RankedStrategy(family_id: str, modifier_ids: list[str], fit: FitLevel, why: list[str], expected_cost_class: str | None, name: str)`
  - `prefilter_families(docs: list[PatternDoc], *, profile: TaskProfile, available_capabilities: set[str], anti_hit_ids: set[str] | None = None, limit: int = 5) -> list[StrategyCandidate]` — drops `status!="active"`, unmet `required_capabilities`, and docs whose `id` is in `anti_hit_ids`
  - `fit_level_from_score(score: float) -> FitLevel` — High if `>=0.75`, Medium if `>=0.4`, else Low (pinned for this plan; not shown as %)
  - `rank_strategies(candidates: list[StrategyCandidate], scores: dict[str, float], why_by_id: dict[str, list[str]]) -> list[RankedStrategy]` — sort High→Low then score desc; stable by `family_id`
  - `autonomy_decidable(ranked: list[RankedStrategy], *, min_fit: FitLevel = "High", require_margin: bool = True) -> bool` — True iff non-empty, top.fit >= min_fit, and (not require_margin or len==1 or top.fit > ranked[1].fit with High>Medium>Low order)

- [ ] **Step 1: Write failing tests** covering planned exclusion, capability exclusion, fit banding, autonomy margin true/false, empty→False

- [ ] **Step 2: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_coding_agent_selection.py -v` — expect FAIL (module missing)

- [ ] **Step 3: Implement helpers**

- [ ] **Step 4: Run tests** — PASS

- [ ] **Step 5: Commit** `feat(coding_agent): pure pattern selection helpers`

---

### Task 2: Active launch-family catalog YAML

**Files:**
- Create: `coding_agent/patterns/families/plan_then_execute.yaml`, `tdd.yaml`, `debug.yaml`, `review_only.yaml`
- Keep: `react.yaml` active; `orchestrator_workers.yaml` planned
- Test: extend `tests/test_coding_agent_pattern_schema.py`

**Interfaces:**
- Produces: five **active** families loadable via `load_patterns(FAMILIES_DIR)` with distinct `when_to_use` / `anti_criteria` / `expected_cost_class` / `runner` keys matching ids (`plan_then_execute`, `tdd`, `debug`, `review_only`, `react`)
- `review_only.allowed_tools` omits write tools (`edit` absent)
- Still only ReAct runner code exists (Phase 3)

- [ ] **Step 1: Failing test** `test_launch_catalog_has_five_active_families` asserting active ids == frozenset({...}) and planned still excludes `orchestrator_workers`

- [ ] **Step 2: Add YAML docs** (selection metadata only; steps can be minimal lists)

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(patterns): active launch catalog for selection`

---

### Task 3: `agent_runs` selection columns + CRUD

**Files:**
- Modify: `daemon/models.py` (`AgentRunRecord`), `daemon/registry.py` (CREATE + ALTER list + create/update/get mapping)
- Test: extend `tests/test_agent_runs_registry.py`

**Interfaces:**
- Produces new nullable/default columns on `agent_runs` (ALTER-add if missing, same pattern as `agent_settings`):
  - `schema_version INTEGER NOT NULL DEFAULT 1`
  - `pattern_versions_json TEXT NOT NULL DEFAULT '{}'`
  - `recommended_json TEXT`
  - `chosen_source TEXT` (`user` \| `auto` \| `fallback_default`)
  - `user_override INTEGER NOT NULL DEFAULT 0`
  - `stage1_profile_json TEXT`
  - `fit_levels_json TEXT`
  - `selection_scores_json TEXT`
  - `selection_filter_provider TEXT`, `selection_judgment_provider TEXT`
  - `selection_filter_skipped INTEGER`, `selection_judgment_skipped INTEGER`
  - `selection_skip_reason TEXT`
- `status` may be `pending_selection` \| `running` \| … (existing values remain valid)
- Extend `create_agent_run(...)` and `update_agent_run(...)` to accept/patch the selection fields above
- `AgentRunRecord` gains matching optional fields with defaults

- [ ] **Step 1: Failing tests** — create with selection payload; update chosen_source; legacy DB without columns opens via ALTER

- [ ] **Step 2: Implement migration + CRUD**

- [ ] **Step 3: pytest** `tests/test_agent_runs_registry.py -v` — PASS

- [ ] **Step 4: Commit** `feat(registry): persist pattern selection on agent_runs`

---

### Task 4: Autonomy settings fields

**Files:**
- Modify: `daemon/models.py` (`AgentSettings`, `AgentSettingsUpdate`), `daemon/registry.py` (`agent_settings` ALTER columns + get/update), `daemon/api.py` (pass-through validation)
- Test: extend settings tests (`tests/test_agent_api.py` or dedicated settings test module already used for decision providers)

**Interfaces:**
- Produces settings columns/fields:
  - `selection_autonomy_enabled` bool default `True`
  - `autonomy_min_fit` TEXT default `"High"` (only `High`\|`Medium`\|`Low`)
  - `autonomy_require_margin` bool default `True`
- PUT rejects invalid `autonomy_min_fit` with HTTP 400

- [ ] **Step 1: Failing tests** for defaults + validation

- [ ] **Step 2: Implement**

- [ ] **Step 3: pytest** targeted — PASS

- [ ] **Step 4: Commit** `feat(settings): pattern selection autonomy defaults`

---

### Task 5: Daemon Stage 1/2 selection pipeline

**Files:**
- Create: `daemon/pattern_selection.py`
- Test: `tests/test_pattern_selection.py` (mock DecisionClient; no live HTTP)

**Interfaces:**
- Consumes: Task 1 helpers, `PatternRegistry`, `DecisionClient` via `build_decision_clients`
- Produces:
  - `SelectionPreview` dataclass/Pydantic: `ranked: list[RankedStrategy]` (max 3 for display field `top3`), `auto_decidable: bool`, `fallback: bool`, `stage1_profile: TaskProfile`, `recommended: RankedStrategy | None`, raw score/provider/skip telemetry fields
  - `async def preview_strategies(*, task_instruction: str, acceptance_criteria: str, registry: PatternRegistry, relevance: DecisionClient, judgment: DecisionClient, available_capabilities: set[str], autonomy_min_fit: FitLevel = "High", autonomy_require_margin: bool = True, stage2_max: int = 5) -> SelectionPreview`
- Stage 1: call `relevance.judge` or `filter_relevance` with `pack="pattern_stage1"` and candidates describing profile labels; on skip → `TaskProfile(type="feature", size="med", risk="med", has_tests=False, repo_familiarity="unknown")` + `fallback` path that ranks only `react` as High why=`["selection_fallback"]`
- Prefilter active families → ≤ `stage2_max` candidates (always include `react` if present and not already included when candidates empty)
- Stage 2: `judgment.judge` with `pack="pattern_stage2"`, catalog=candidate summaries (`id`, `when_to_use`, `anti_criteria`); map scores through `fit_level_from_score`; on skip → same ReAct fallback
- Never raise to caller for provider failures — catch, set skip_reason, fallback

- [ ] **Step 1: Failing tests** — happy path ranks 3; skip→react fallback; planned excluded; autonomy flags

- [ ] **Step 2: Implement `pattern_selection.py`**

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(daemon): two-stage pattern selection pipeline`

---

### Task 6: Preview + Implement API and runtime lock

**Files:**
- Modify: `daemon/agent_runtime.py`, `daemon/api.py`, `daemon/models.py` (request/response models)
- Test: extend `tests/test_agent_api.py`

**Interfaces:**
- Produces:
  - `POST /api/projects/{project_id}/tasks/{task_id}/implement/preview` → `SelectionPreview` JSON (does **not** spawn worker; may create no row, or a `pending_selection` row — **pin: no row**; preview is stateless)
  - `ImplementRequest`: `choice: Literal["user","auto"]`, `family_id: str | None = None`, `modifier_ids: list[str] = []`
  - `POST .../implement` accepts optional JSON body (default body ≡ `{choice:"auto"}` for backward compat)
  - Behavior:
    1. Run `preview_strategies`
    2. If `choice=="auto"` and not `auto_decidable` and settings.selection_autonomy_enabled → **HTTP 409** with preview body (no spawn)
    3. If `choice=="auto"` and decidable (or autonomy disabled with fallback) → pick `recommended` or `react`
    4. If `choice=="user"` → require `family_id` among active ids (else 400); `user_override = (family_id != recommended.family_id)`
    5. `_open_coding_run` writes manifest with locked `family_id`, `modifier_ids`, `runner_fallback: bool` (`True` if runner key != `react`), selection telemetry; `create_agent_run` with selection columns; `status=running`; then existing `_route_task_execution`
  - `chosen_source`: `user` | `auto` | `fallback_default`

- [ ] **Step 1: Failing tests** — preview shape; implement user pick; auto 409 when not decidable; auto success; empty-body still works (compat); fallback_default when clients skip

- [ ] **Step 2: Wire runtime + API**

- [ ] **Step 3: pytest** `tests/test_agent_api.py -v` — PASS

- [ ] **Step 4: Commit** `feat(api): implement preview and strategy lock`

---

### Task 7: Worker honors `family_id` + runner_fallback event

**Files:**
- Modify: `daemon/agent_run.py`
- Test: extend `tests/test_agent_run_loop.py` (or equivalent)

**Interfaces:**
- Consumes: manifest `family_id`, optional `runner_fallback`
- Produces: still runs `ReactRunner` in Phase 2; if `family_id != "react"` or `runner_fallback`, emit JSONL event `{ "type": "strategy.runner_fallback", "family_id": ..., "executed_runner": "react" }` before the loop
- Does not import new runners

- [ ] **Step 1: Failing test** for fallback event when `family_id=tdd`

- [ ] **Step 2: Implement**

- [ ] **Step 3: pytest** — PASS

- [ ] **Step 4: Commit** `feat(agent_run): emit runner_fallback for non-react picks`

---

### Task 8: Dashboard Implement picker

**Files:**
- Create: `dashboard/components/implement-picker-modal.tsx`
- Modify: `dashboard/components/task-detail-drawer.tsx`, `dashboard/components/suggestion-chip.tsx`, `dashboard/lib/api.ts`
- Modify: `messages/en.json`, `messages/ar.json`
- Read Next 16 guidance under `dashboard/node_modules/next/dist/docs/` before coding if App Router APIs are touched (client component only expected)

**Interfaces:**
- Produces:
  - `previewImplement(projectId, taskId) -> SelectionPreview`
  - `implementTask(projectId, taskId, body?: ImplementRequest) -> AgentTask | SelectionPreview` — on 409, parse preview JSON and rethrow/return typed conflict
  - Modal shows top 3: name, fit badge, cost band, why bullets; actions: pick one, **Let agent decide**
  - Chip/drawer Implement: call preview; if `auto_decidable && selection_autonomy_enabled` (from settings cache or preview flag), POST `{choice:"auto"}` immediately; else open modal
  - On pick: POST `{choice:"user", family_id}`; on Let agent decide: POST `{choice:"auto"}` (if 409, keep modal open with message)

- [ ] **Step 1: Add API client types + i18n keys** (`implement.picker.title`, `.fit.high|medium|low`, `.letAgentDecide`, `.why`, `.cost`, `.autonomyBlocked`)

- [ ] **Step 2: Build modal + wire Implement buttons**

- [ ] **Step 3: `cd dashboard && npm run lint`** — clean for touched files

- [ ] **Step 4: Commit** `feat(dashboard): Implement pattern picker`

---

### Task 9: Dashboard autonomy settings UI

**Files:**
- Modify: `dashboard/components/agent-settings-panel.tsx`, `dashboard/lib/api.ts`, `messages/{en,ar}.json`

**Interfaces:**
- Produces: toggles/fields for `selection_autonomy_enabled`, `autonomy_min_fit`, `autonomy_require_margin` bound to existing settings PUT

- [ ] **Step 1: Extend AgentSettings types + panel controls + i18n**

- [ ] **Step 2: lint**

- [ ] **Step 3: Commit** `feat(dashboard): selection autonomy settings`

---

### Task 10: Regression gate

**Files:** none new

- [ ] **Step 1: Run** `PYTHONPATH=. .venv/bin/pytest tests/` — PASS

- [ ] **Step 2: Run** `cd dashboard && npm run lint` — PASS

- [ ] **Step 3: Fix breakages** without expanding into Phase 3 runners / learning / overlays

- [ ] **Step 4: Commit** only if fixes needed: `fix: keep suite green after phase-2 selection`

---

## Spec coverage (Phase 2)

| Spec item | Task |
|-----------|------|
| §5.1 Selection at Implement only | 6, 8 |
| §5.2 Stage 1 profile + prefilter | 1, 5 |
| §5.3 Stage 2 shortlist scores; High/Med/Low | 1, 5 |
| §5.4 Top 3 + Let agent decide + autonomy | 4, 5, 6, 8, 9 |
| §5.5 Log recommended vs chosen | 3, 6 |
| Fallback ReAct; never block on provider failure | 5, 6 |
| §7.2 selection columns | 3 |
| `coding_agent` import-clean | 1 (guard) |
| Active catalog for meaningful shortlist | 2 |
| Phase 3 real runners | Deferred (`runner_fallback`) |

## Out of this plan

Real Plan-then-Execute / TDD / Debug / Review-only runners (Phase 3); verification judges (Phase 4); learning write-path (Phase 5); project overlays (Phase 6–7); extraction/SaaS (Phase 8); calibrated % fit; modifiers YAML pack (ship empty `modifier_ids` unless trivial); Suggest/Accept changes.
