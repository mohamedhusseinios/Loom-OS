# Loom Agent + Jev Orchestration Loop — Design

**Date:** 2026-11-13 (Decision model addendum: 2026-11-14)  
**Status:** Approved (design) — Decision model section approved in brainstorming 2026-11-14  
**Related:**
- `docs/superpowers/specs/2026-06-27-agentic-os-kanban-task-board-design.md`
- `docs/superpowers/specs/2026-06-28-multi-agent-worker-runners-design.md`
- Plan: `docs/superpowers/plans/2026-11-14-pluggable-decision-model.md`

---

## 1. Summary

Add a first-party **Loom agent** in the dashboard that:

1. Chats with the user about Kanban board tasks.
2. Runs an **orchestration loop** over project **graph memory**: a pluggable **decision layer** filters/ranks graph hits and helps choose next actions; a **main chat model** (default DeepSeek; BYOK + pluggable OpenAI-compatible models) writes human-language replies and suggestion prose.
3. Suggests the next step for human **Accept / Dismiss** (nothing executes until the user acts).
4. **Implements** via hybrid handoff: assign `loom-agent`, move task to Running, existing `loom worker` runs in a git worktree.

### Decision model (2026-11-14)

The decision layer is user-selectable and provider-agnostic inside the orchestrator:

| Provider id | Role in Phase 1 | Wire format |
|-------------|-----------------|-------------|
| `typesafe` | Filter + judgment (default when key set) | TypeSafe cloud `POST /v1/systemone` |
| `ollama` | Filter + judgment | Same SystemOne client; local base URL (default `http://localhost:11434`); API key optional; **model required** (e.g. `nimble`) |
| `gliclass` | **Filter only** | Separate process: Knowledgator `python -m gliclass.serve` → `POST /gliclass`. **Do not load torch in the daemon.** |
| `none` | Filter and/or judgment | No HTTP; filter → top hybrid hits; judgment → escalate |

Judgments with GLiClass are out of scope until benchmark numbers justify promotion.

---

## 2. Decisions

| Fork | Decision |
|------|----------|
| Suggest vs auto-run | Suggest-only until Accept / Implement |
| Main chat model | DeepSeek by default; user API key; add other OpenAI-compatible models |
| Decision layer | Pluggable behind `DecisionClient`; orchestrator never branches on provider id |
| UI vs storage for roles | UI shape **B** (one Decision model selector + Judgment backend when GLiClass); storage **C** (`filter_provider` + `judgment_provider`) for a later dual-selector without migration |
| Judgment default | Jev cloud (`typesafe`) if a key is set; else `none` → escalate |
| Filter default with no key | `filter_provider=none` (top hybrid hits; honest skip telemetry; no failing call every cycle) |
| typesafe + ollama | One SystemOne client (`JevClient`); differ only by config |
| GLiClass Phase 1 | Relevance filter only; judgment stays on typesafe/ollama/none |
| Thresholds | Per-provider code defaults; optional overrides in settings; **no UI** until after first benchmark |
| Context source | Project graph via `GraphEngine.hybrid_query` (+ task fields / findings) |
| Next-step catalog | Status-valid Loom actions + optional `loom-playbook.json` + graph-cited candidates |
| Triggers | Auto on Ready / Blocked / leave Running + manual Suggest / chat |
| Implement path | Hybrid: chat/loop plans; worker executes |

---

## 3. Architecture

```
Dashboard Loom Agent UI
    │  chat / suggest / accept / implement / settings (Decision model)
    ▼
Daemon agent_runtime
    │
    ▼
resolve_decision_config(settings) → DecisionConfig
build_decision_clients(config)    → (relevance_client, judgment_client)
    │  cache keyed by hash(DecisionConfig); reuse one instance if both roles match
    │  judgment=none → NullDecisionClient (judge returns skipped; no None checks)
    ▼
orchestrator.run_suggest_cycle
    │ 1. hybrid_query (broad)
    │ 2. relevance_client.filter_relevance  (+ 30s filter cache key includes provider+model)
    │ 3. Main model when required (see escalation below)
    │ 4. judgment_client.judge (+ post-escalation grounding pass)
    │ 5. map_judgments_to_action → persist suggestion + WS
    ▼
SQLite (chats, suggestions, settings) + existing task APIs
    │
    └─ Implement → assignee=loom-agent, status=running → loom worker worktree
```

### Escalation (step 3) — precise

Call DeepSeek when any of:

- relevance or judgment result is **skipped**;
- winning score is below the provider’s **escalate** threshold;
- a key noul is in that provider’s **mid-band**;
- `NullDecisionClient` / `judgment_provider=none` in **auto-suggest** (always escalate).

After DeepSeek produces new candidates, run a **grounding pass**: those candidates go through `judgment_client.judge` for `grounded_*` before `map_judgments_to_action`.

### Component responsibilities

| Unit | Purpose | Depends on |
|------|---------|------------|
| `decision` protocol + factory | `DecisionClient`, `resolve_decision_config`, `build_decision_clients` | `agent_settings` |
| `jev_client` | SystemOne for `typesafe` and `ollama` | settings then env |
| `gliclass_client` | Knowledgator `POST /gliclass` (filter only) | settings (URL + model) |
| `null_decision_client` | Skipped judgment (and unused filter) | — |
| `llm_client` | OpenAI-compatible chat | settings / env |
| `orchestrator` | One suggest/chat cycle | graph_engine, two DecisionClients, llm, registry |
| `agent_runtime` | Chat history + suggest/implement glue | orchestrator, registry |
| Dashboard panel | Chat, suggestion chip, Decision model + BYOK settings | REST + WS |

---

## 4. Data model

### Tables (in `~/.loom/state.db`)

**`agent_settings`** (singleton row `id=1`):

- `default_model` TEXT (e.g. `deepseek-chat`)
- `providers_json` TEXT — list of `{id, name, base_url, model_ids[]}`
  - Stable provider ids: `typesafe`, `ollama`, `gliclass` (plus existing chat providers e.g. `deepseek`)
- `api_keys_json` TEXT — map provider_id → api_key (never returned raw on GET)
- `filter_provider` TEXT — `typesafe` \| `ollama` \| `gliclass` \| `none`
- `judgment_provider` TEXT — `typesafe` \| `ollama` \| `none` (`gliclass` **rejected** in Phase 1)
- `threshold_overrides_json` TEXT NULL — optional per-provider overrides; absent → code defaults

**Lazy defaults (no forced migration):** legacy rows without role fields resolve via `resolve_decision_config()`:

- typesafe key present → `filter_provider=typesafe`, `judgment_provider=typesafe`
- no typesafe key → `filter_provider=none`, `judgment_provider=none`

**`agent_chats`**: `id`, `project`, `task_id` NULLABLE, `created_at`, `updated_at`

**`agent_messages`**: `id`, `chat_id`, `role` (`user`/`assistant`/`system`), `content`, `created_at`

**`task_suggestions`**: existing columns retained; **new columns added alongside** (do not drop `jev_*` in this release):

| Column | Notes |
|--------|--------|
| `filter_provider`, `filter_model` | Who filtered |
| `judgment_provider`, `judgment_model` | Who judged (`none` allowed) |
| `filter_skipped`, `judgment_skipped` | Booleans |
| `filter_skip_reason`, `judgment_skip_reason` | `none` \| `error` \| `timeout` \| `bad_payload` \| `unsupported` \| NULL if not skipped |
| `filter_input_tokens`, `judgment_input_tokens` | Nullable (GLiClass/none → NULL) |
| `filter_latency_ms`, `judgment_latency_ms` | From normalized result |
| `effective_thresholds_json` | Resolved keep/mid/drop/escalate used this cycle |
| `legacy_decision_input_tokens` | For old rows: copy of historical combined `jev_input_tokens`; new per-role token columns stay NULL on migrated rows |

**Legacy columns** (`jev_skipped`, `jev_input_tokens`, …): keep writing/reading compatibility only as needed during transition; **API, dashboard, and cost report switch to the new columns**. Drop old columns in a later release (SQLite rebuild).

Unique constraint: at most one `pending` suggestion per `task_id`.

### Playbook file

Optional `{project_path}/loom-playbook.json`:

```json
{
  "steps": [
    {"id": "playbook.write_tests", "label": "Write failing tests first", "when": ["todo", "ready"]}
  ]
}
```

---

## 5. API

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects/{id}/agent/chat` | `{message, task_id?, chat_id?}` → reply + optional suggestion |
| POST | `/api/projects/{id}/tasks/{tid}/suggest` | Manual suggest |
| POST | `/api/projects/{id}/suggestions/{sid}/accept` | Apply Loom action if applicable; 409 if stale |
| POST | `/api/projects/{id}/suggestions/{sid}/dismiss` | Mark dismissed |
| POST | `/api/projects/{id}/tasks/{tid}/implement` | Assign `loom-agent`, status Running |
| GET/PUT | `/api/agent/settings` | Masked keys + `has_keys`; Decision model fields; auth as for other settings |

WebSocket events: `agent:message`, `task:suggestion`.

PUT validation:

- `filter_provider` / `judgment_provider` must reference role-allowed provider ids.
- `judgment_provider=gliclass` → 400 in Phase 1.
- Selecting Decision model Jev/Ollama in the UI sets **both** roles to that provider.
- Selecting GLiClass sets `filter_provider=gliclass` and uses Judgment backend for `judgment_provider`.
- Switching **from** GLiClass **back** to Jev/Ollama **resets** `judgment_provider` to that same provider (do not keep a stale judgment value).
- Ollama: model required; `base_url` defaults to `http://localhost:11434`; API key optional.

---

## 6. Orchestration loop details

1. **Retrieve** — `hybrid_query(project_path, project, question=task.title + instruction)` top_k broad.
2. **Empty graph** — if no hits and no graph.json, return guidance to build graph; do not invent context.
3. **Resolve clients** — `resolve_decision_config` + `build_decision_clients` (cached until `DecisionConfig` hash changes).
4. **Relevance filter** — `relevance_client.filter_relevance(...)`. Apply **effective** thresholds for the filter provider: keep / mid-band / drop. Missing per-question scores → **mid-band** (uncertain), not drop; unknown keys ignored. On skipped (`none` \| error \| timeout \| bad_payload \| unsupported): use top-N hybrid hits; record skip reason. **Filter cache** (~30s) key must include provider + model.
5. **Main model** — given filtered pack + chat history, produce assistant reply and optional candidate option labels (must cite graph node ids). Called for real chat, or when escalation rules in §3 fire.
6. **Catalog** — merge status-valid Loom actions + playbook steps + cited candidates; dedupe by id.
7. **Judgment** — `judgment_client.judge(...)` (atomic complete/blocked/ready_to_implement/grounded_*). Null → skipped → escalate in auto-suggest. Post-escalation grounding pass uses the same judgment client.
8. **Map** — `map_judgments_to_action` → Loom `move_*`.
9. **Persist** — replace any existing pending suggestion; store providers, models, skips, reasons, tokens, latencies, effective thresholds; emit WS.

### Loom action allowlist by status (examples)

- `todo` → `move_ready`, `move_blocked`
- `ready` → `move_running`, `move_blocked`
- `running` → `move_blocked`, `move_done`
- `blocked` → `move_ready`, `move_todo`
- `done` → `move_archived`

Accept of a Loom `move_*` action calls existing `update_agent_task`. Non-Loom actions mark accepted and surface prose only.

---

## 7. DecisionClient contract

### Protocol

- `filter_relevance(...)` → `DecisionResult`
- `judge(...)` → `DecisionResult`

### `DecisionResult` (normalized)

| Field | Meaning |
|-------|---------|
| `scores` | Per-question key → float in `[0, 1]` (empty if skipped) |
| `usage` | Tokens nullable (`input_tokens: int \| null`) |
| `provider` | `typesafe` \| `ollama` \| `gliclass` \| `none` |
| `model` | Configured model id (empty for Null) |
| `skipped` | Bool |
| `skip_reason` | `none` \| `error` \| `timeout` \| `bad_payload` \| `unsupported` \| null |
| `latency_ms` | Wall time for the call |

### Implementations

| Client | Notes |
|--------|--------|
| `JevClient` | Shared SystemOne for typesafe + ollama; retries as today; cloud timeout ~10s, local ~5s |
| `GLiClassClient` | Hard-coded Knowledgator serve shape `POST /gliclass` (texts, labels, threshold); Phase 1 `judge` → skipped/`unsupported` if ever called; no torch in daemon |
| `NullDecisionClient` | `judge` always skipped/`none`; orchestrator has no `None` checks |

### Thresholds

- Per-provider code defaults (Jev keeps today’s 0.7 keep / 0.3 drop semantics; GLiClass has its own documented defaults).
- Optional `threshold_overrides` in settings; valid only if `0 <= drop < mid < keep <= 1`; invalid → defaults + logged warning.
- Persist **effective** thresholds on each `task_suggestion`.
- No threshold UI until after the first benchmark.

### Errors

Provider down / HTTP error / bad payload → that client returns skipped + reason + log; **never crash the cycle**.

---

## 8. Keys & providers

- Main chat model and decision providers are configured from dashboard **Agent settings** (BYOK). Environment variables remain a fallback only.
- Resolution order: dashboard settings first, then env (`TYPESAFE_API_KEY` / `TYPESAFE_BASE_URL`, `DEEPSEEK_API_KEY`, etc.).
- All decision config reads go through **`resolve_decision_config()`** so a later nested `decision` object touches one place.
- Keys stored in `api_keys_json` as plaintext on the local daemon DB (existing BYOK path; no at-rest encryption). GET never returns raw secrets; masking as today.
- Settings changes are read on every chat/suggest cycle; client cache invalidated when `DecisionConfig` hash changes (includes keys, URLs, models, thresholds).

---

## 9. Worker / `loom-agent`

- Register in `known_agents` as always-available (no CLI detect required for dashboard agent).
- Runner: `loom` CLI subcommand or `python -m daemon.agent_run` that executes the task instruction in the worktree using `llm_client` (stdout mode), budget-aware where possible.
- Implement endpoint sets assignee to project-scoped `loom-agent` id pattern consistent with other agents.

---

## 10. Dashboard

- Project-level **Loom Agent** chat panel (optional `task_id` from selected card).
- Task card: suggestion chip (action, confidence, prose) + Accept / Dismiss / Implement.
- Settings (`AgentSettingsPanel`): default model; DeepSeek key + base URL; **Decision model** selector (Jev cloud / Local Ollama / GLiClass); provider-specific fields (key, base URL, model); when GLiClass selected, **Judgment backend** (Jev cloud / Local Ollama / None→escalate); masked secrets; set/clear.
- No threshold fields in UI in Phase 1.
- i18n: `en` + `ar`.

---

## 11. Measurement & benchmark

- Extend `scripts/agent_cost_report.py` to report by filter/judgment provider+model; include skip rates by reason, latency, escalation, accept/dismiss.
- GLiClass decision-token `$` is n/a or 0; still report latency and skip rates.
- **`--benchmark`**: fixed task set; compare providers on tokens/$, latency, escalation rate, filter/judgment skip rates, accept/dismiss rate.
- Do **not** promote GLiClass to judgments until benchmark numbers justify it.

---

## 12. Guards

- Single-flight pending suggestion per task; auto-trigger cooldown (~30s).
- Accept re-reads task status; 409 if incompatible with action.
- Never log raw API keys.
- Drop candidates without graph citations.
- Missing main-model key → HTTP 400 with settings hint.
- Decision clients never crash the suggest cycle.
- Phase 1: reject `judgment_provider=gliclass`.

---

## 13. Testing

- Shared **DecisionClient contract suite** (mocked HTTP) for Jev/typesafe, Jev/ollama, GLiClass, Null: result shape, skip reasons, latency, error paths, missing scores → mid-band, unknown keys ignored.
- Unit: `resolve_decision_config`, factory cache/reuse, filter cache key includes provider+model, threshold validation, orchestrator escalation + grounding (mocked).
- **Migration test:** DB with legacy `jev_*` rows opens cleanly; old columns preserved; new per-role columns NULL; `legacy_decision_input_tokens` populated from old `jev_input_tokens`.
- API/settings: Decision model round-trip; gliclass-as-judgment rejected; masked secrets; en+ar strings.
- Full suite: `PYTHONPATH=. .venv/bin/pytest tests/`; dashboard `npm run lint` and `npm run build`.
- No live provider calls in CI.
- **Optional manual smoke** (not CI): script that calls each locally configured provider once (typesafe, ollama, gliclass) to verify real wire format matches mocks.

---

## 14. Out of scope

- Fully autonomous Implement without Accept
- Cloud multi-user key vault
- Replacing Claude/Codex CLI runners
- Fine-tuning GLiClass; image inputs; bundling model weights
- GLiClass for judgments (until benchmarks justify)
- Threshold UI (until after first benchmark)
- Nested `decision` settings object (centralize reads now; reshape later)
- Dropping legacy `jev_*` columns (later release)
- Plugin / entry-point registry for third-party decision backends
- Configurable GLiClass path/field mapping beyond Knowledgator serve defaults
