# Pluggable Decision Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Loom Agent decision layer pluggable (typesafe / ollama / gliclass / none) with dual filter+judgment roles, normalized telemetry, and dashboard Decision model settings — without the orchestrator knowing which provider it talks to.

**Architecture:** Introduce a `DecisionClient` protocol + `resolve_decision_config` / `build_decision_clients` factory (per-cycle, config-hash cache, instance reuse). `JevClient` serves typesafe and ollama; `GLiClassClient` is filter-only against Knowledgator serve; `NullDecisionClient` covers `none`. Extend `agent_settings` and `task_suggestions` alongside legacy `jev_*` columns; switch readers to new fields; update dashboard + cost/benchmark tooling.

**Tech Stack:** FastAPI/aiosqlite daemon, urllib HTTP clients, pytest (mocked HTTP), Next.js dashboard + next-intl.

**Spec:** `docs/superpowers/specs/2026-11-13-loom-agent-orchestration-loop-design.md`

## Global Constraints

- Orchestrator never branches on provider id
- No torch / GLiClass weights inside the daemon
- Phase 1: `judgment_provider=gliclass` rejected
- Legacy `jev_*` columns kept; new columns added alongside
- Full suite: `PYTHONPATH=. .venv/bin/pytest tests/`; dashboard `npm run lint` + `npm run build`
- No live provider calls in CI; optional smoke script is manual-only
- Do not push / open / merge PRs without explicit user approval
- i18n: every new UI string in both `messages/en.json` and `messages/ar.json`

## Review Focus

- Legacy DB with only `jev_*` suggestion columns opens and serves API without null errors → Task 2 migration test
- Switching Decision model GLiClass → Ollama resets `judgment_provider` to `ollama` (not stale typesafe/none) → Task 6 API/UI test
- Filter cache hit after changing provider/model must miss (key includes provider+model) → Task 5
- Invalid threshold override (`keep < mid`) logs warning and uses defaults; suggestion stores effective defaults → Task 3 + 5
- GLiClass HTTP 500 → `filter_skipped` + `skip_reason=error`, cycle completes with hybrid top hits → Task 4 + 5

## File map

| Path | Responsibility |
|------|----------------|
| `daemon/decision.py` (new) | Protocol, `DecisionResult`, `DecisionConfig`, `NullDecisionClient`, `resolve_decision_config`, `build_decision_clients`, threshold helpers, client cache |
| `daemon/jev_client.py` | Conform to protocol; optional key for ollama; timeouts; latency/skip_reason |
| `daemon/gliclass_client.py` (new) | Knowledgator `POST /gliclass` filter client |
| `daemon/orchestrator.py` | Use two clients; escalation + grounding; filter cache key; persist new telemetry |
| `daemon/agent_runtime.py` | Build clients from settings each cycle (or call factory) |
| `daemon/models.py` | Settings + suggestion fields |
| `daemon/registry.py` | Columns, CRUD, migration of legacy rows |
| `daemon/api.py` | Settings GET/PUT validation for roles |
| `dashboard/components/agent-settings-panel.tsx` | Decision model UI (B over storage C) |
| `dashboard/lib/api.ts`, `messages/{en,ar}.json` | Types + i18n |
| `scripts/agent_cost_report.py` | New columns + multi-provider `--benchmark` |
| `scripts/decision_provider_smoke.py` (new) | Manual live smoke (not CI) |
| `tests/test_decision_contract.py` (new) | Shared contract suite |
| `tests/test_decision_config.py` (new) | resolve + factory + thresholds |
| `tests/...` | Extend registry/orchestrator/api/settings tests |

---

### Task 1: Decision protocol, Null client, result shape

**Files:**
- Create: `daemon/decision.py`
- Test: `tests/test_decision_contract.py` (Null cases first)

**Interfaces:**
- Produces: `DecisionResult`, `DecisionClient` protocol with `filter_relevance` / `judge`, `NullDecisionClient`, `SkipReason` literals

- [ ] **Step 1: Write failing tests** for `NullDecisionClient.judge` → `skipped=True`, `skip_reason="none"`, `provider="none"`, `usage.input_tokens is None`, `latency_ms >= 0`

- [ ] **Step 2: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_decision_contract.py -v` — expect FAIL (module missing)

- [ ] **Step 3: Implement** protocol + `DecisionResult` + `NullDecisionClient` in `daemon/decision.py`

- [ ] **Step 4: Run tests** — expect PASS

- [ ] **Step 5: Commit** `feat(decision): add DecisionClient protocol and NullDecisionClient`

---

### Task 2: Settings + suggestion schema (alongside legacy columns)

**Files:**
- Modify: `daemon/models.py`, `daemon/registry.py`
- Test: `tests/test_agent_orchestrator_registry.py` (add migration test)

**Interfaces:**
- Consumes: existing `AgentSettings` / `TaskSuggestionRecord` patterns
- Produces: `filter_provider`, `judgment_provider`, `threshold_overrides` on settings; new suggestion telemetry fields; `legacy_decision_input_tokens` backfill

- [ ] **Step 1: Write failing migration test** — open DB with legacy `task_suggestions` (`jev_skipped`, `jev_input_tokens` only); after `initialize()`, assert old columns exist, new per-role token columns are NULL, `legacy_decision_input_tokens ==` old `jev_input_tokens`

- [ ] **Step 2: Run test** — expect FAIL

- [ ] **Step 3: Add columns via existing `PRAGMA table_info` + `ALTER TABLE` pattern; extend models and insert/select mappers; do **not** map `jev_input_tokens` → `filter_input_tokens`

- [ ] **Step 4: Extend settings** with `filter_provider`, `judgment_provider`, `threshold_overrides_json` + default `ollama`/`gliclass` provider rows; GET/PUT models

- [ ] **Step 5: Run** registry/settings tests — PASS

- [ ] **Step 6: Commit** `feat(decision): add filter/judgment settings and suggestion telemetry columns`

---

### Task 3: `resolve_decision_config` + thresholds + factory cache

**Files:**
- Modify: `daemon/decision.py`
- Test: `tests/test_decision_config.py`

**Interfaces:**
- Produces: `DecisionConfig`, `resolve_decision_config(settings, raw_keys) -> DecisionConfig`, `build_decision_clients(config) -> tuple[DecisionClient, DecisionClient]`, `effective_thresholds(provider) -> dict`, config hash for cache

- [ ] **Step 1: Failing tests** for: no key → filter/judgment `none`; key → both `typesafe`; `gliclass` judgment rejected/falls back with warning; invalid overrides → defaults; same provider+config → identical client instance; config hash changes when model/URL/key/thresholds change

- [ ] **Step 2: Implement** resolve + threshold validation (`0 <= drop < mid < keep <= 1`) + factory with reuse + cache keyed by full config hash

- [ ] **Step 3: Run** `tests/test_decision_config.py` — PASS

- [ ] **Step 4: Commit** `feat(decision): resolve_decision_config and client factory`

---

### Task 4: JevClient protocol conformance + GLiClassClient

**Files:**
- Modify: `daemon/jev_client.py`
- Create: `daemon/gliclass_client.py`
- Test: `tests/test_decision_contract.py`, `tests/test_jev_llm_clients.py` (extend)

**Interfaces:**
- Consumes: `DecisionClient` / `DecisionResult`
- Produces: SystemOne client usable as typesafe or ollama (key optional for ollama); GLiClass filter via `POST /gliclass`

- [ ] **Step 1: Contract tests** (mocked HTTP) for Jev/typesafe, Jev/ollama, GLiClass: shape, `latency_ms`, error→`skip_reason=error`, timeout→`timeout`, bad JSON→`bad_payload`; GLiClass `judge` → `unsupported`

- [ ] **Step 2: Adapt `JevClient`** to return `DecisionResult`; timeouts ~10s cloud / ~5s local; keep retries

- [ ] **Step 3: Implement `GLiClassClient`** against Knowledgator serve request/response; no torch import

- [ ] **Step 4: Wire factory** to construct these clients; run contract suite — PASS

- [ ] **Step 5: Commit** `feat(decision): Jev and GLiClass DecisionClient implementations`

---

### Task 5: Orchestrator wiring

**Files:**
- Modify: `daemon/orchestrator.py`, `daemon/agent_runtime.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `build_decision_clients`, effective thresholds, `DecisionResult`
- Produces: cycle uses two clients; persists new telemetry; escalation + grounding per spec §3/§6

- [ ] **Step 1: Failing tests** for: filter `none` → hybrid top hits + `filter_skip_reason=none`; mid-band / escalate threshold triggers LLM; Null judgment auto-suggest escalates; post-escalation grounding calls `judgment_client.judge`; missing scores treated as mid-band; filter cache key includes provider+model

- [ ] **Step 2: Refactor** `_jev_filter` / judgment paths to protocol clients; rename internals away from hard-coded jev where appropriate; keep behavior

- [ ] **Step 3: Persist** new suggestion fields (providers, models, skips, reasons, tokens, latencies, `effective_thresholds_json`); stop treating combined tokens as filter-only

- [ ] **Step 4: Run** orchestrator + related tests — PASS

- [ ] **Step 5: Commit** `feat(decision): wire orchestrator to pluggable DecisionClients`

---

### Task 6: API + dashboard Decision model UI

**Files:**
- Modify: `daemon/api.py`, `dashboard/components/agent-settings-panel.tsx`, `dashboard/lib/api.ts`, `dashboard/messages/en.json`, `dashboard/messages/ar.json`
- Test: `tests/test_agent_api.py`, `tests/test_agent_settings_runtime.py`

**Interfaces:**
- Consumes: settings fields from Task 2
- Produces: UI shape B; storage still two fields; GLiClass→Jev/Ollama resets judgment

- [ ] **Step 1: API tests** — PUT `judgment_provider=gliclass` → 400; Ollama without model → 400; Decision model fields round-trip; masked keys unchanged

- [ ] **Step 2: Implement API validation** + GET includes filter/judgment providers

- [ ] **Step 3: Dashboard** — Decision model selector + conditional Judgment backend + ollama/gliclass fields; on leave GLiClass, set judgment to selected provider; en+ar strings

- [ ] **Step 4: Run** API tests; `cd dashboard && npm run lint && npm run build`

- [ ] **Step 5: Commit** `feat(decision): Decision model settings API and dashboard UI`

---

### Task 7: Cost report, benchmark, migration polish, smoke script

**Files:**
- Modify: `scripts/agent_cost_report.py`, `daemon/agent_cost.py` (if present)
- Create: `scripts/decision_provider_smoke.py`
- Test: `tests/test_agent_cost.py`

**Interfaces:**
- Consumes: new suggestion columns
- Produces: report/benchmark by provider; smoke script excluded from CI

- [ ] **Step 1: Update cost summarizer** to use `filter_input_tokens` + `judgment_input_tokens`; GLiClass `$` n/a; skip rates by reason

- [ ] **Step 2: Extend `--benchmark`** to compare configured decision providers on the fixed task set (tokens/$, latency, escalation, skip rates, accept/dismiss if available)

- [ ] **Step 3: Add** `scripts/decision_provider_smoke.py` — one live call per configured provider (typesafe/ollama/gliclass); document “manual only”

- [ ] **Step 4: Run** `PYTHONPATH=. .venv/bin/pytest tests/ -v` and dashboard lint/build

- [ ] **Step 5: Commit** `feat(decision): cost report, benchmark, and manual provider smoke`

---

### Task 8: Final verification

- [ ] **Step 1:** `PYTHONPATH=. .venv/bin/pytest tests/ -v` — all green
- [ ] **Step 2:** `cd dashboard && npm run lint && npm run build` — pass
- [ ] **Step 3:** Spec self-check — every Decision model requirement maps to a task above
- [ ] **Step 4:** Commit any leftover doc-only fixes if needed (no PR/push)
