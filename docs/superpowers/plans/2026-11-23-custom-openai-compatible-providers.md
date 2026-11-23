# Custom OpenAI-Compatible Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users add/remove multiple OpenAI-compatible providers in Agent settings and use them for coding chat and/or decision filter/judgment, without breaking built-in DeepSeek / TypeSafe / Ollama / GLiClass.

**Architecture:** Extend `AgentProviderConfig` with `kind`. User rows are `openai_compatible` and merge by `id` into existing `providers_json` / `api_keys_json`. Chat resolution prefers a provider whose `model_ids` contains `default_model` (deepseek or openai_compatible); decision treats custom ids like today’s Ollama path via `JevClient`. Dashboard adds a custom-provider list; API validates slug, collision, model, and in-use delete.

**Tech Stack:** Python 3 / pytest / FastAPI / Pydantic, Next.js 16 + next-intl (`en`/`ar`), existing `JevClient` / `LlmClient`.

**Spec:** `docs/superpowers/specs/2026-11-23-custom-openai-compatible-providers-design.md`

## Global Constraints

- Custom providers are OpenAI-compatible only (no new TypeSafe/GLiClass kinds)
- Builtin ids: `deepseek`, `typesafe`, `ollama`, `gliclass` — never overwritten by custom create
- Custom `id`: lowercase `[a-z0-9_-]+`, length ≥ 2; immutable after create (API may still accept same-id overwrite of other fields)
- `judgment_provider=gliclass` remains rejected
- GET settings never returns raw API keys
- Delete (or drop) of a custom provider still referenced by filter/judgment/`default_model` → HTTP 400
- DeepSeek fallback when `default_model` matches no provider’s `model_ids` stays (existing unlisted-model behavior)
- Full suite: `PYTHONPATH=. .venv/bin/pytest tests/`; after UI: `cd dashboard && npm run lint`
- i18n: every new UI string in both `messages/en.json` and `messages/ar.json`
- Do not push / open / merge without explicit user approval
- Function signatures stay on one line (project convention)

## Review Focus

- Unlisted `default_model` on DeepSeek-only settings still uses DeepSeek base URL + key → Task 1
- Custom `default_model` listed only on a custom provider never falls through to DeepSeek URL → Task 1
- Custom id colliding with `ollama` (or any builtin) rejected at PUT → Task 3
- Removing custom provider still selected as filter → 400, provider retained → Task 3
- Decision custom id builds `JevClient` with that base URL/model (ollama-equivalent thresholds) → Task 2

## File map

| Path | Responsibility |
|------|----------------|
| `daemon/models.py` | Optional `kind` on `AgentProviderConfig` |
| `daemon/agent_credentials.py` | Builtin set, kind normalize, chat resolution, merge/ensure preserve custom |
| `daemon/decision.py` | Allow custom filter/judgment ids; endpoint + client like ollama |
| `daemon/api.py` | PUT validation for custom providers + in-use delete |
| `dashboard/components/agent-settings-panel.tsx` | Custom providers UI |
| `dashboard/lib/api.ts` | `kind?` on provider type |
| `dashboard/messages/{en,ar}.json` | `LoomAgent` custom-provider strings |
| `tests/test_loom_agent_runner.py` (or new `tests/test_agent_credentials.py`) | Chat resolution + merge |
| `tests/test_decision_config.py` | Custom decision roles |
| `tests/test_agent_api.py` | PUT accept/reject cases |

---

### Task 1: Kind helpers + chat resolution

**Files:**
- Modify: `daemon/models.py` — add `kind: Optional[str] = None` on `AgentProviderConfig`
- Modify: `daemon/agent_credentials.py`
- Test: `tests/test_loom_agent_runner.py` (add cases beside existing `test_llm_from_stored_*`) **or** create `tests/test_agent_credentials.py` if preferred for clarity

**Interfaces:**
- Consumes: existing `StoredAgentCredentials`, `merge_providers`, `ensure_default_providers`
- Produces:
  - `BUILTIN_PROVIDER_IDS: frozenset[str]` = `{deepseek, typesafe, ollama, gliclass}`
  - `PROVIDER_KIND_BUILTIN = "builtin"`, `PROVIDER_KIND_OPENAI = "openai_compatible"`
  - `def normalize_provider_kind(provider: dict[str, Any]) -> dict[str, Any]` — sets `kind` from id if missing; forces builtin ids to `builtin`
  - `def is_valid_custom_provider_id(provider_id: str) -> bool` — fullmatch `^[a-z0-9_-]{2,}$` and not in `BUILTIN_PROVIDER_IDS`
  - `ensure_default_providers` / `merge_providers` — run `normalize_provider_kind` on every row; preserve custom rows
  - `StoredAgentCredentials.llm_from_stored(self) -> tuple[str, str, str]` — **first** prefer provider where `default_model in model_ids` and (`id == deepseek` or `kind == openai_compatible`); **else** existing DeepSeek-row fallback (including unlisted model on deepseek base)

- [ ] **Step 1: Write failing tests**

```python
def test_llm_from_stored_resolves_openai_compatible_model():
    from daemon.agent_credentials import StoredAgentCredentials
    creds = StoredAgentCredentials(
        default_model="llama-3.1-8b",
        providers=[
            {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"], "kind": "builtin"},
            {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"},
        ],
        keys={"deepseek": "sk-deep", "openrouter": "sk-or"},
    )
    key, base, model = creds.llm_from_stored()
    assert (key, base, model) == ("sk-or", "https://openrouter.ai/api/v1", "llama-3.1-8b")


def test_merge_providers_preserves_custom_openai_compatible():
    from daemon.agent_credentials import merge_providers
    merged = merge_providers([], [{"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1", "model_ids": ["llama-3.1-70b"], "kind": "openai_compatible"}])
    groq = next(p for p in merged if p["id"] == "groq")
    assert groq["kind"] == "openai_compatible"
    assert "deepseek" in {p["id"] for p in merged}


def test_is_valid_custom_provider_id():
    from daemon.agent_credentials import is_valid_custom_provider_id
    assert is_valid_custom_provider_id("openrouter") is True
    assert is_valid_custom_provider_id("ollama") is False
    assert is_valid_custom_provider_id("A") is False
```

Keep existing `test_llm_from_stored_uses_custom_deepseek_base_url_for_unlisted_model` green (DeepSeek fallback).

- [ ] **Step 2: Run tests — expect FAIL** on missing helpers / wrong chat resolution

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_loom_agent_runner.py::test_llm_from_stored_resolves_openai_compatible_model tests/test_loom_agent_runner.py::test_merge_providers_preserves_custom_openai_compatible -v` (adjust path if using new file)

- [ ] **Step 3: Implement helpers + `llm_from_stored` preference + `kind` on model**

- [ ] **Step 4: Run tests — expect PASS** including the existing unlisted-model DeepSeek test

- [ ] **Step 5: Commit**

```bash
git add daemon/models.py daemon/agent_credentials.py tests/test_loom_agent_runner.py
# or tests/test_agent_credentials.py if created
git commit -m "$(cat <<'EOF'
feat(agent): resolve chat LLM from openai_compatible providers

EOF
)"
```

---

### Task 2: Decision config for custom provider ids

**Files:**
- Modify: `daemon/decision.py`
- Test: `tests/test_decision_config.py`

**Interfaces:**
- Consumes: provider rows with `kind` / custom ids from Task 1; existing `_role_endpoint` / `_build_one` ollama branch
- Produces:
  - `_resolve_roles` accepts filter/judgment values that are builtins **or** an id present in settings providers with `kind=openai_compatible` (or inferred custom)
  - `_role_endpoint(provider, ...)` for custom ids: same as ollama (require model, base_url from row, key by id, ollama thresholds)
  - `_build_one(provider, ...)` for custom ids: same as ollama → `JevClient(..., provider="ollama"|custom, ...)` — use `provider="ollama"` **or** pass the custom id string if `JevClient` only uses it for logging; pin in test via `isinstance(..., JevClient)` + `base_url` / `model` attributes
  - Missing custom id at resolve time → fall back to `none` with warning (PUT should prevent this)

- [ ] **Step 1: Write failing tests**

```python
def test_custom_openai_compatible_filter_and_judgment():
    settings = _settings(
        filter_provider="openrouter",
        judgment_provider="openrouter",
        providers=[{
            "id": "openrouter",
            "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model_ids": ["llama-3.1-8b"],
            "kind": "openai_compatible",
        }],
    )
    config = resolve_decision_config(settings, {"openrouter": "sk-or"})
    assert config.filter_provider == "openrouter"
    assert config.judgment_provider == "openrouter"
    assert config.filter_model == "llama-3.1-8b"
    assert config.filter_base_url == "https://openrouter.ai/api/v1"
    assert config.filter_api_key == "sk-or"
    relevance, judgment = build_decision_clients(config)
    assert isinstance(relevance, JevClient)
    assert relevance is judgment
    assert "openrouter.ai" in (relevance.base_url or "")


def test_custom_provider_requires_model_like_ollama():
    settings = _settings(
        filter_provider="groq",
        judgment_provider="none",
        providers=[{"id": "groq", "base_url": "https://api.groq.com/openai/v1", "model_ids": [], "kind": "openai_compatible"}],
    )
    with pytest.raises(ValueError, match="model"):
        resolve_decision_config(settings, {})
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_decision_config.py::test_custom_openai_compatible_filter_and_judgment -v`

- [ ] **Step 3: Implement** widen `_FILTER_PROVIDERS` / `_JUDGMENT_PROVIDERS` checks (or replace closed-set membership with helper `def _is_allowed_decision_provider(provider_id: str, rows: list, *, for_judgment: bool) -> bool`)

- [ ] **Step 4: Run — expect PASS**; existing decision tests still green

Run: `PYTHONPATH=. .venv/bin/pytest tests/test_decision_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add daemon/decision.py tests/test_decision_config.py
git commit -m "$(cat <<'EOF'
feat(decision): allow openai_compatible custom provider roles

EOF
)"
```

---

### Task 3: API validation for custom providers

**Files:**
- Modify: `daemon/api.py` — `_validate_decision_settings` and/or new `_validate_custom_providers`
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Consumes: `merge_providers`, `is_valid_custom_provider_id`, Task 1 kinds
- Produces: PUT `/api/agent/settings` behavior:
  - Accept custom provider + `filter_provider`/`judgment_provider` set to that id when model set
  - 400 if custom id invalid slug or collides with builtin
  - 400 if custom row missing `base_url` or model
  - 400 if judgment=`gliclass` (unchanged)
  - 400 if payload’s merged providers would **drop** a custom id that current settings still use as filter, judgment, or whose model is current `default_model` (when `providers` is sent). Detail string must mention the provider id.
  - Extend ollama-style “requires a model” check to custom ids used in roles

- [ ] **Step 1: Write failing tests** (follow existing `client` fixture patterns in `test_agent_api.py`)

```python
def test_put_settings_accepts_custom_openai_compatible_provider(client):
    resp = client.put("/api/agent/settings", json={
        "default_model": "llama-3.1-8b",
        "filter_provider": "openrouter",
        "judgment_provider": "openrouter",
        "providers": [{
            "id": "openrouter", "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible",
        }],
        "api_keys": {"openrouter": "sk-or"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["filter_provider"] == "openrouter"
    assert body["has_keys"]["openrouter"] is True
    custom = next(p for p in body["providers"] if p["id"] == "openrouter")
    assert custom["base_url"].startswith("https://openrouter.ai")


def test_put_settings_rejects_custom_id_colliding_with_builtin(client):
    resp = client.put("/api/agent/settings", json={
        "providers": [{
            "id": "ollama", "name": "Fake", "base_url": "http://x", "model_ids": ["m"],
            "kind": "openai_compatible",
        }],
    })
    assert resp.status_code == 400


def test_put_settings_rejects_removing_custom_provider_in_use(client):
    client.put("/api/agent/settings", json={
        "default_model": "llama-3.1-8b",
        "filter_provider": "openrouter",
        "judgment_provider": "none",
        "providers": [{
            "id": "openrouter", "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible",
        }],
    })
    # Send providers list with only builtins intent: omit openrouter while still referencing it
    resp = client.put("/api/agent/settings", json={
        "filter_provider": "openrouter",
        "providers": [{"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]}],
    })
    # Spec: reject drop while in use. If merge_providers keeps unspecified existing rows,
    # simulate delete by a dedicated signal OR document that UI must send explicit tombstone.
    # Pin chosen mechanism in implementation: prefer rejecting when payload includes
    # `providers` that list only a subset AND sets `remove_provider_ids` — OR simpler:
    # reject when filter/judgment/default_model references an id absent from *merged* result
    # after applying an explicit `"providers"` replace mode.
```

**Pin the delete mechanism (spec: reject delete while in use):**

Use optional write field on update payload: `remove_provider_ids: list[str] | None = None` on `AgentSettingsUpdate`. When set, remove those ids from merged providers **after** merge, then validate no role/`default_model` still references them; else 400 and do not persist. UI delete calls PUT with `remove_provider_ids: ["openrouter"]`.

Add model field + test:

```python
def test_put_settings_remove_provider_ids_blocked_when_in_use(client):
    client.put("/api/agent/settings", json={
        "filter_provider": "openrouter",
        "judgment_provider": "none",
        "providers": [{
            "id": "openrouter", "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible",
        }],
    })
    blocked = client.put("/api/agent/settings", json={"remove_provider_ids": ["openrouter"]})
    assert blocked.status_code == 400
    client.put("/api/agent/settings", json={"filter_provider": "none", "judgment_provider": "none", "default_model": "deepseek-chat"})
    ok = client.put("/api/agent/settings", json={"remove_provider_ids": ["openrouter"]})
    assert ok.status_code == 200
    assert all(p["id"] != "openrouter" for p in ok.json()["providers"])
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement** `remove_provider_ids` on `AgentSettingsUpdate`, validation helpers, wire `registry.update_agent_settings` to apply removals

- [ ] **Step 4: Run** `PYTHONPATH=. .venv/bin/pytest tests/test_agent_api.py -k custom_openai -v` and broader agent settings tests

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py daemon/models.py daemon/registry.py tests/test_agent_api.py
git commit -m "$(cat <<'EOF'
feat(api): validate and remove custom openai_compatible providers

EOF
)"
```

---

### Task 4: Dashboard custom providers UI

**Files:**
- Modify: `dashboard/components/agent-settings-panel.tsx`
- Modify: `dashboard/lib/api.ts` — `kind?: string` on providers; `remove_provider_ids?: string[]` on update type
- Modify: `dashboard/messages/en.json`, `dashboard/messages/ar.json` under `LoomAgent`
- Read Next 16 docs under `dashboard/node_modules/next/dist/docs/` only if App Router patterns for this panel change (client component already)

**Interfaces:**
- Consumes: Task 3 PUT contract
- Produces: UI section “Custom providers” listing `kind === "openai_compatible"` rows; Add (name, id, base URL, model, optional key); Edit fields except id; Delete → PUT `remove_provider_ids`; Clear key; include custom rows in save `providers` array; decision `<select>` options include custom ids; default model can be set to a custom model id

i18n keys (add both locales): `customProvidersTitle`, `customProviderAdd`, `customProviderName`, `customProviderId`, `customProviderBaseUrl`, `customProviderModel`, `customProviderKey`, `customProviderDelete`, `customProviderInUseError` (and reuse existing key status strings where possible).

- [ ] **Step 1: Extend API types + i18n keys (en + ar)**

- [ ] **Step 2: Implement panel section + wire save/delete/decision options**

- [ ] **Step 3: Verify** `cd dashboard && npm run lint`

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/agent-settings-panel.tsx dashboard/lib/api.ts dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "$(cat <<'EOF'
feat(dashboard): manage custom openai_compatible agent providers

EOF
)"
```

---

### Task 5: Regression gate

**Files:** none new

- [ ] **Step 1: Run** `PYTHONPATH=. .venv/bin/pytest tests/ -q` — PASS

- [ ] **Step 2: Run** `cd dashboard && npm run lint` — PASS

- [ ] **Step 3: Fix breakages** without expanding scope (no encryption, no new decision kinds)

- [ ] **Step 4: Commit only if fixes needed**

```bash
git commit -m "$(cat <<'EOF'
fix: keep suite green after custom providers

EOF
)"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| `kind` + many openai_compatible rows | 1 |
| Chat resolves custom `default_model` | 1 |
| DeepSeek unlisted-model fallback | 1 (existing test) |
| Decision custom filter/judgment like ollama | 2 |
| PUT validation / collision / model | 3 |
| Reject delete while in use (`remove_provider_ids`) | 3 |
| Dashboard list add/edit/delete + i18n | 4 |
| Suite green | 5 |

## Out of this plan

At-rest key encryption; TypeSafe/GLiClass custom kinds; full generic provider registry; mid-run provider switch; calibrated cost claims.
