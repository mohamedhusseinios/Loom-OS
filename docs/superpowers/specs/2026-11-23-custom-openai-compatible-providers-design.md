# Custom OpenAI-Compatible Providers — Design

**Date:** 2026-11-23  
**Status:** Approved (written-spec review 2026-11-23)  
**Related:**
- `daemon/agent_credentials.py` — provider merge, `llm_from_stored`, key masking
- `daemon/decision.py` — filter/judgment roles, `build_decision_clients`
- `daemon/api.py` — `PUT /api/agent/settings` provider validation
- `dashboard/components/agent-settings-panel.tsx` — Agent settings UI
- Coding agent chat path: `daemon/agent_runtime.py`, `daemon/agent_run.py`, `daemon/supervisor.py`

---

## 1. Summary

Allow users to **add and remove multiple OpenAI-compatible providers** in Loom Agent settings. Each custom provider can be used for:

1. **Chat / coding loop** — BYOK OpenAI-compatible chat (today effectively only the `deepseek` row).
2. **Decision filter and/or judgment** — uses the **SystemOne protocol** (`JevClient`, same as `ollama`: `POST <base_url>/v1/systemone` with `{model, state, questions}`), **not** OpenAI chat completions. A custom provider used for a decision role must point at a SystemOne-compatible server.

Built-in providers (`deepseek`, `typesafe`, `ollama`, `gliclass`) remain. Custom providers are **OpenAI-compatible for chat only** (`/v1/chat/completions`-style); decision roles are SystemOne-compatible (see above). No new TypeSafe or GLiClass kinds in this work.

### Non-negotiable constraints

- Filesystem inbox + single-process daemon unchanged.
- GET settings never returns raw API keys (masked + `has_keys` only).
- Existing DeepSeek / TypeSafe / Ollama / GLiClass installs keep working with empty custom list.
- `judgment_provider=gliclass` remains rejected.
- Do not push or merge unless explicitly asked.
- Existing test suite must stay green.

---

## 2. Decisions (from brainstorming)

| Fork | Decision |
|------|----------|
| Scope | Both chat and decision roles |
| Protocol | OpenAI-compatible only (option A) |
| Shape | Many user-added providers (approach 2), not a single `custom` slot or full generic registry |
| Built-ins | Keep four defaults; do not fold TypeSafe/GLiClass into openai_compatible |
| Delete while in use | Reject save with HTTP 400 (UI can warn) |
| Custom id after create | Immutable; edit name / base_url / model_ids / key only |
| Optional API key | Allowed (local servers); model id still required for decision roles |

---

## 3. Data model

### 3.1 Provider row

Extend `AgentProviderConfig`:

| Field | Type | Notes |
|-------|------|--------|
| `id` | string | Stable slug. Built-ins unchanged. Custom: lowercase `[a-z0-9_-]+`, length ≥ 2. |
| `name` | string | Display label |
| `base_url` | string | OpenAI-compatible API root |
| `model_ids` | `list[str]` | Custom rows require ≥1 non-empty model id |
| `kind` | `"builtin"` \| `"openai_compatible"` | Built-ins are `builtin`. User-added are `openai_compatible`. |

API keys remain in `api_keys_json` keyed by provider `id` (plaintext at rest — same as today’s DeepSeek BYOK; encrypting keys is out of scope).

`ensure_default_providers` / `merge_providers` continue to merge by `id`. Custom rows are preserved across ensures; builtins are appended if missing.

### 3.2 Kind inference

- Known builtin ids → `kind=builtin` (even if client omits `kind`).
- Unknown ids on write → treat as `openai_compatible` (explicit `kind` preferred).
- Reject custom `id` that collides with a builtin id.

### 3.3 Roles

| Role | Setting | Allowed values |
|------|---------|----------------|
| Chat model | `default_model` | Any model id listed on `deepseek` or on a `kind=openai_compatible` provider |
| Filter | `filter_provider` | `typesafe` \| `ollama` \| `gliclass` \| `none` \| custom provider `id` |
| Judgment | `judgment_provider` | `typesafe` \| `ollama` \| `none` \| custom provider `id` (not `gliclass`) |

---

## 4. Resolution & runtime

### 4.1 Chat (`StoredAgentCredentials.llm_from_stored`)

1. Find a provider whose `model_ids` contains `default_model`.
2. If found and that provider is `deepseek` **or** `kind=openai_compatible`, use that row’s `base_url` and `api_keys[id]`.
3. If no match, keep today’s DeepSeek fallback (`deepseek` base URL + key + `default_model`) so existing installs do not break.

Supervisor / worker continue to pass resolved key, `LOOM_AGENT_BASE_URL`, and model into the coding agent; no new env vars.

### 4.2 Decision (`resolve_decision_config` / `build_decision_clients`)

- Allow filter/judgment provider ids that are builtins (as today) **or** ids of stored `openai_compatible` providers.
- For a custom id, `_role_endpoint` behaves like `ollama`: require a non-empty first model, use that row’s `base_url` and key, use ollama-equivalent thresholds.
- `_build_one` for custom ids uses the same client construction as `ollama` (`JevClient` with that base URL / key / model). **Note:** this is the SystemOne wire protocol, not chat completions; a plain OpenAI endpoint (e.g. OpenRouter) will 404 on `/v1/systemone` and decisions skip with `reason=error`. The dashboard copy states this requirement. `DecisionResult.provider` stays `"ollama"` for custom ids because `JevClient` remaps unknown ids to `typesafe`.
- `DecisionConfig.cache_hash` already includes URL/key/model → custom endpoints cache correctly.
- Unknown role ids that are not builtins and not present as custom providers → fall back to `none` with a warning (or reject at PUT time so this path is defensive only).

### 4.3 PUT `/api/agent/settings` validation

- Reject custom id colliding with builtin.
- Reject custom row with empty `base_url` or empty `model_ids`.
- Reject invalid custom id slug.
- Reject `judgment_provider=gliclass`.
- Reject filter/judgment pointing at a missing provider id.
- Reject filter/judgment pointing at a custom provider with no model set.
- Reject removing (or omitting-from-merge in a way that drops) a custom provider that is still selected as filter, judgment, or whose model is still `default_model` → **HTTP 400** with a clear detail string.
- Same-id save overwrites the custom row (no duplicates).

---

## 5. Dashboard UX

In `agent-settings-panel.tsx` (and i18n `en` + `ar`):

- Keep existing DeepSeek and decision builtin blocks.
- Add **Custom providers** section:
  - List current `kind=openai_compatible` rows (name, base URL, model, key status).
  - **Add:** name, id (suggested slug from name; editable before first save), base URL, model, optional API key.
  - **Edit:** name, base URL, model, key (id immutable after create).
  - **Clear key** / **Delete** (delete blocked by API if in use; show error message).
- Decision model dropdown includes custom provider ids (and judgment excludes gliclass as today).
- Default model input (or select) can use models from DeepSeek and custom providers.
- On save, include custom rows in `providers` payload alongside builtins that the panel already sends.

---

## 6. Testing

| Area | Coverage |
|------|----------|
| Credentials | Custom rows survive `ensure_default_providers` / `merge_providers`; `llm_from_stored` resolves custom `default_model` to that base URL/key; DeepSeek fallback when unmatched |
| API | Accept custom + roles; reject collision, bad slug, missing model, judgment=gliclass, delete/in-use |
| Decision | `resolve_decision_config` + `build_decision_clients` for a custom id use the ollama-style SystemOne path (mock `JevClient` or endpoint fields) |
| Regression | Existing agent settings / decision provider tests stay green |

Dashboard component tests are optional for v1 if API + credentials + decision coverage is solid.

---

## 7. Out of scope

- At-rest encryption of API keys  
- Custom TypeSafe / GLiClass (non-OpenAI) kinds  
- Provider marketplace or shared org catalogs  
- Mid-run provider / model switching  
- Folding all builtins into a single generic registry (approach 3)  
- Calibrated cost/accuracy claims for custom endpoints  

---

## 8. Success criteria

1. User can add ≥1 OpenAI-compatible provider and run the coding chat loop on it via `default_model`.
2. The same or another custom provider can be selected as filter and/or judgment, provided it serves the SystemOne protocol (documented in the UI and spec).
3. Built-in DeepSeek / TypeSafe / Ollama / GLiClass paths keep working with no custom rows.
4. GET never returns raw secrets; full `pytest` suite green.

---

## 9. Implementation notes (for the plan)

Primary touch points (expected):

- `daemon/models.py` — optional `kind` on `AgentProviderConfig`
- `daemon/agent_credentials.py` — kind helpers, chat resolution order
- `daemon/decision.py` — widen allowed provider ids; custom endpoint like ollama
- `daemon/api.py` — PUT validation
- `dashboard/components/agent-settings-panel.tsx` + `messages/{en,ar}.json`
- Tests under `tests/test_agent_api.py`, credentials/decision tests as applicable

Prefer small TDD slices: credentials resolution → API validation → decision wiring → dashboard UI.
