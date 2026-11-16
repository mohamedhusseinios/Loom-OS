"""API tests for Loom agent chat, suggest, accept, implement, settings."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import daemon.api as api_module
from daemon.graph_engine import GraphEngine
from daemon.llm_client import LlmError
from daemon.models import AgentInfo, AgentTaskCreatePayload, AgentTaskStatus
from daemon.orchestrator import SuggestResult
from daemon.registry import AgentRegistry


@pytest.fixture
async def client(tmp_path):
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()
    await registry.upsert_project("noor", str(tmp_path / "noor"))
    await registry.upsert_agent(AgentInfo(
        agent_id="claude-code-noor", agent_name="claude-code",
        version="1.0", project="noor", capabilities=[],
    ))
    api_module.registry = registry
    api_module.graph_engine = GraphEngine()
    api_module.router = None
    api_module.watcher = None
    api_module.supervisor = None
    api_module.agent_runtime = None
    api_module.LOOM_INBOX_BASE = str(tmp_path / "inbox")
    with TestClient(api_module.app) as c:
        yield c
    await registry.close()


def test_settings_put_and_masked_get(client):
    res = client.put("/api/agent/settings", json={
        "api_keys": {"deepseek": "sk-abcdef1234"},
        "default_model": "deepseek-chat",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["api_keys_masked"]["deepseek"] == "••••1234"
    assert body["has_keys"]["deepseek"] is True
    assert "sk-abcdef1234" not in res.text
    get = client.get("/api/agent/settings")
    assert get.json()["api_keys_masked"]["deepseek"] == "••••1234"
    assert get.json()["has_keys"]["deepseek"] is True
    assert "sk-abcdef1234" not in get.text


def test_chat_without_key_returns_400(client):
    res = client.post("/api/projects/noor/agent/chat", json={"message": "hi"})
    assert res.status_code == 400
    assert "API key" in res.json()["detail"]


@pytest.mark.asyncio
async def test_suggest_accept_loom_action(client, tmp_path):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Fix bug", instruction="fix null",
    ))
    fake = SuggestResult(
        action_id="loom.move_ready",
        action_label="Move task to Ready",
        confidence=0.8,
        prose="Promote to ready",
        catalog=[{"id": "loom.move_ready", "label": "Move task to Ready"}],
        reply="Promote to ready",
    )
    with patch.object(api_module.AgentRuntime, "suggest", return_value=None):
        # create suggestion via registry then accept
        sug = await reg.create_task_suggestion(
            "noor", tid, "loom.move_ready", "Move task to Ready", 0.8, "go", [],
        )
        res = client.post(f"/api/projects/noor/suggestions/{sug.id}/accept")
        assert res.status_code == 200
        task = await reg.get_agent_task(tid)
        assert task.status == AgentTaskStatus.READY


@pytest.mark.asyncio
async def test_implement_sets_running_loom_agent(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Impl", instruction="do it",
    ))
    # move to ready first so implement from todo is still ok
    await reg.update_agent_task(tid, status=AgentTaskStatus.READY)
    with patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "running"
    assert body["assignee"] == "loom-agent-noor"


@pytest.mark.asyncio
async def test_implement_dismisses_pending_suggestion(client):
    """Implement must clear pending suggestions so Accept cannot 409 later."""
    from daemon.models import SuggestionStatus

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Impl", instruction="do it",
    ))
    await reg.update_agent_task(tid, status=AgentTaskStatus.READY)
    sug = await reg.create_task_suggestion(
        "noor", tid, "loom.move_running", "Move to Running", 0.9, "go", [],
    )
    with patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert res.status_code == 200
    pending = await reg.get_pending_suggestion(tid)
    assert pending is None
    updated = await reg.get_task_suggestion(sug.id)
    assert updated is not None
    assert updated.status == SuggestionStatus.DISMISSED
    accept = client.post(f"/api/projects/noor/suggestions/{sug.id}/accept")
    assert accept.status_code == 400


@pytest.mark.asyncio
async def test_dismiss_suggestion(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="X", instruction="y",
    ))
    sug = await reg.create_task_suggestion(
        "noor", tid, "loom.move_blocked", "Block", 0.5, "no", [],
    )
    res = client.post(f"/api/projects/noor/suggestions/{sug.id}/dismiss")
    assert res.status_code == 200
    assert res.json()["status"] == "dismissed"


@pytest.mark.asyncio
async def test_dismiss_rejects_non_pending_suggestion(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="X", instruction="y",
    ))
    sug = await reg.create_task_suggestion(
        "noor", tid, "loom.move_ready", "Ready", 0.8, "go", [],
    )
    accept = client.post(f"/api/projects/noor/suggestions/{sug.id}/accept")
    assert accept.status_code == 200
    dismiss = client.post(f"/api/projects/noor/suggestions/{sug.id}/dismiss")
    assert dismiss.status_code == 400
    assert "not pending" in dismiss.json()["detail"]


@pytest.mark.asyncio
async def test_running_workspace_patch_does_not_trigger_suggest(client):
    """Worker workspace_path-only PATCH must not kick off auto-suggest."""
    from unittest.mock import patch

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Run", instruction="work",
    ))
    await reg.update_agent_task(tid, status=AgentTaskStatus.RUNNING, assignee="loom-agent-noor")

    with patch("daemon.api.asyncio.create_task") as create_task:
        res = client.patch(
            f"/api/projects/noor/tasks/{tid}",
            json={"workspace_path": "/tmp/wt"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "running"
        assert res.json()["workspace_path"] == "/tmp/wt"
        create_task.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_leave_running_schedules_suggest(client):
    """Leaving Running with an explicit status still schedules auto-suggest."""
    from unittest.mock import AsyncMock, patch

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Done soon", instruction="work",
    ))
    await reg.update_agent_task(tid, status=AgentTaskStatus.RUNNING, assignee="loom-agent-noor")

    scheduled = []

    def capture(coro):
        scheduled.append(coro)
        return AsyncMock()  # stand-in Task

    with patch.object(api_module.AgentRuntime, "suggest", new_callable=AsyncMock) as suggest:
        with patch("daemon.api.asyncio.create_task", side_effect=capture):
            res = client.patch(
                f"/api/projects/noor/tasks/{tid}",
                json={"status": "blocked", "result": "{}"},
            )
        assert res.status_code == 200
        assert res.json()["status"] == "blocked"
        assert len(scheduled) == 1
        await scheduled[0]
        suggest.assert_awaited()


def test_settings_typesafe_and_clear(client, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    secret = "ts-secret-key-9999"
    res = client.put("/api/agent/settings", json={
        "api_keys": {"typesafe": secret, "deepseek": "sk-abcdef1234"},
        "providers": [{
            "id": "typesafe", "name": "TypeSafe (Jev)",
            "base_url": "http://localhost:11434", "model_ids": ["jev-latest"],
        }],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["api_keys_masked"]["typesafe"] == "••••9999"
    assert body["api_keys_masked"]["deepseek"] == "••••1234"
    assert body["has_keys"]["typesafe"] is True
    assert body["has_keys"]["deepseek"] is True
    assert secret not in res.text
    assert "sk-abcdef1234" not in res.text
    typesafe = next(p for p in body["providers"] if p["id"] == "typesafe")
    assert typesafe["base_url"] == "http://localhost:11434"

    got = client.get("/api/agent/settings")
    assert got.status_code == 200
    data = got.json()
    assert data["has_keys"]["typesafe"] is True
    assert secret not in got.text
    assert "api_keys" not in data or data.get("api_keys") is None

    cleared = client.put("/api/agent/settings", json={"api_keys": {"typesafe": ""}})
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["has_keys"]["typesafe"] is False
    assert "typesafe" not in (body.get("api_keys_masked") or {})
    assert body["has_keys"]["deepseek"] is True
    # typesafe provider (and its base URL) is kept after clearing the key
    typesafe = next(p for p in body["providers"] if p["id"] == "typesafe")
    assert typesafe["base_url"] == "http://localhost:11434"


def test_settings_ignores_masked_placeholder(client):
    client.put("/api/agent/settings", json={"api_keys": {"deepseek": "sk-live-key-4242"}})
    res = client.put("/api/agent/settings", json={"api_keys": {"deepseek": "••••4242"}})
    assert res.status_code == 200
    raw_get = client.get("/api/agent/settings")
    assert raw_get.json()["api_keys_masked"]["deepseek"] == "••••4242"
    assert raw_get.json()["has_keys"]["deepseek"] is True


def test_settings_requires_auth_when_enabled(client):
    from daemon.auth import configure_auth_token
    client.put("/api/agent/settings", json={"api_keys": {"deepseek": "sk-auth-secret-7777"}})
    configure_auth_token("settings-token")
    try:
        denied_get = client.get("/api/agent/settings")
        assert denied_get.status_code == 401
        assert "sk-auth-secret-7777" not in denied_get.text
        denied_put = client.put("/api/agent/settings", json={"api_keys": {"typesafe": "should-not-store"}})
        assert denied_put.status_code == 401
        ok = client.get(
            "/api/agent/settings",
            headers={"Authorization": "Bearer settings-token"},
        )
        assert ok.status_code == 200
        assert ok.json()["has_keys"]["deepseek"] is True
        assert "sk-auth-secret-7777" not in ok.text
        assert ok.json()["api_keys_masked"]["deepseek"] == "••••7777"
    finally:
        configure_auth_token(None)


def test_get_settings_typesafe_has_key_from_env(client, monkeypatch):
    """GLiClass judgment defaults from has_keys, so an env-only TypeSafe key must count."""
    secret = "ts-env-only-key-4242"
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    missing = client.get("/api/agent/settings")
    assert missing.status_code == 200
    assert missing.json()["has_keys"]["typesafe"] is False

    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    res = client.get("/api/agent/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["has_keys"]["typesafe"] is True
    assert secret not in res.text
    assert not (body.get("api_keys_masked") or {}).get("typesafe")


def test_get_settings_includes_decision_providers(client):
    res = client.get("/api/agent/settings")
    assert res.status_code == 200
    body = res.json()
    assert "filter_provider" in body
    assert "judgment_provider" in body
    assert body["filter_provider"] is None
    assert body["judgment_provider"] is None


def test_judgment_provider_gliclass_rejected(client):
    res = client.put("/api/agent/settings", json={
        "filter_provider": "gliclass",
        "judgment_provider": "gliclass",
    })
    assert res.status_code == 400
    assert "gliclass" in res.json()["detail"]
    got = client.get("/api/agent/settings")
    assert got.json()["filter_provider"] is None
    assert got.json()["judgment_provider"] is None

    unknown = client.put("/api/agent/settings", json={"filter_provider": "deepseek"})
    assert unknown.status_code == 400
    bad_judgment = client.put("/api/agent/settings", json={"judgment_provider": "custom"})
    assert bad_judgment.status_code == 400


def test_ollama_without_model_rejected(client):
    res = client.put("/api/agent/settings", json={
        "filter_provider": "ollama",
        "judgment_provider": "ollama",
        "providers": [{
            "id": "ollama", "name": "Ollama",
            "base_url": "http://localhost:11434", "model_ids": ["  "],
        }],
    })
    assert res.status_code == 400
    assert "model" in res.json()["detail"].lower()
    got = client.get("/api/agent/settings")
    assert got.json()["filter_provider"] is None

    ok = client.put("/api/agent/settings", json={
        "filter_provider": "ollama",
        "judgment_provider": "ollama",
        "providers": [{
            "id": "ollama", "name": "Ollama",
            "base_url": "http://localhost:11434", "model_ids": ["nimble"],
        }],
    })
    assert ok.status_code == 200
    body = ok.json()
    assert body["filter_provider"] == "ollama"
    assert body["judgment_provider"] == "ollama"
    ollama = next(p for p in body["providers"] if p["id"] == "ollama")
    assert ollama["model_ids"] == ["nimble"]
    assert ollama["base_url"] == "http://localhost:11434"
    again = client.get("/api/agent/settings")
    assert again.json()["filter_provider"] == "ollama"
    assert again.json()["judgment_provider"] == "ollama"


def test_decision_fields_round_trip_keeps_masked_keys(client):
    secret = "sk-abcdef1234"
    ts = "ts-secret-key-9999"
    seeded = client.put("/api/agent/settings", json={
        "api_keys": {"deepseek": secret, "typesafe": ts},
        "filter_provider": "gliclass",
        "judgment_provider": "none",
    })
    assert seeded.status_code == 200
    res = client.put("/api/agent/settings", json={
        "filter_provider": "gliclass",
        "judgment_provider": "typesafe",
        "providers": [{
            "id": "gliclass", "name": "GLiClass",
            "base_url": "http://127.0.0.1:5555", "model_ids": ["gliclass-v3"],
        }],
        "api_keys": {"deepseek": "••••1234", "typesafe": "••••9999"},
    })
    assert res.status_code == 200
    body = res.json()
    assert body["filter_provider"] == "gliclass"
    assert body["judgment_provider"] == "typesafe"
    assert body["api_keys_masked"]["deepseek"] == "••••1234"
    assert body["api_keys_masked"]["typesafe"] == "••••9999"
    assert secret not in res.text
    assert ts not in res.text
    gliclass = next(p for p in body["providers"] if p["id"] == "gliclass")
    assert gliclass["base_url"] == "http://127.0.0.1:5555"
    assert gliclass["model_ids"] == ["gliclass-v3"]
    got = client.get("/api/agent/settings")
    data = got.json()
    assert data["filter_provider"] == "gliclass"
    assert data["judgment_provider"] == "typesafe"
    assert data["api_keys_masked"]["deepseek"] == "••••1234"
    assert data["has_keys"]["typesafe"] is True
    assert secret not in got.text
    assert ts not in got.text

    rejected = client.put("/api/agent/settings", json={"judgment_provider": "gliclass"})
    assert rejected.status_code == 400
    kept = client.get("/api/agent/settings")
    assert kept.json()["filter_provider"] == "gliclass"
    assert kept.json()["judgment_provider"] == "typesafe"


@pytest.mark.asyncio
async def test_dismiss_emits_suggestion_event(client):
    from daemon.agent_runtime import AgentRuntime
    from daemon.models import SuggestionStatus

    events = []

    async def capture(event, project, data):
        events.append((event, project, data))

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Emit", instruction="y",
    ))
    sug = await reg.create_task_suggestion(
        "noor", tid, "loom.move_blocked", "Block", 0.5, "no", [],
    )
    runtime = AgentRuntime(reg, api_module.graph_engine, emit_event=capture)
    updated = await runtime.dismiss_suggestion("noor", sug.id)
    assert updated.status == SuggestionStatus.DISMISSED
    assert any(e[0] == "task:suggestion" for e in events)


@pytest.mark.asyncio
async def test_implement_emits_dismissed_suggestion_event(client):
    from daemon.agent_runtime import AgentRuntime
    from daemon.models import SuggestionStatus

    events = []

    async def capture(event, project, data):
        events.append((event, project, data))

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Impl emit", instruction="do it",
    ))
    await reg.update_agent_task(tid, status=AgentTaskStatus.READY)
    sug = await reg.create_task_suggestion(
        "noor", tid, "loom.move_running", "Move to Running", 0.9, "go", [],
    )
    runtime = AgentRuntime(reg, api_module.graph_engine, emit_event=capture)
    await runtime.implement("noor", tid, spawn_worker=None)
    suggestion_events = [e for e in events if e[0] == "task:suggestion"]
    assert suggestion_events
    assert suggestion_events[0][2]["id"] == sug.id
    assert suggestion_events[0][2]["status"] == SuggestionStatus.DISMISSED.value
    assert any(e[0] == "task:updated" for e in events)


def test_chat_provider_round_trip(client):
    res = client.put("/api/agent/settings", json={
        "chat_provider": "openai",
        "default_model": "gpt-4o-mini",
        "providers": [{
            "id": "openai",
            "name": "OpenAI",
            "base_url": "https://api.openai.com",
            "model_ids": ["gpt-4o-mini"],
            "api_style": "openai",
        }],
        "api_keys": {"openai": "sk-openai-1234"},
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["chat_provider"] == "openai"
    assert body["default_model"] == "gpt-4o-mini"
    openai = next(p for p in body["providers"] if p["id"] == "openai")
    assert openai["api_style"] == "openai"
    assert body["has_keys"]["openai"] is True
    got = client.get("/api/agent/settings")
    assert got.json()["chat_provider"] == "openai"


def test_chat_provider_rejects_decision_id(client):
    res = client.put("/api/agent/settings", json={"chat_provider": "typesafe"})
    assert res.status_code == 400


def test_list_models_openai_compatible(client, monkeypatch):
    client.put("/api/agent/settings", json={
        "chat_provider": "deepseek",
        "api_keys": {"deepseek": "sk-list-test"},
        "providers": [{
            "id": "deepseek",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model_ids": ["deepseek-chat"],
            "api_style": "openai",
        }],
    })

    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        assert api_key == "sk-list-test"
        assert "deepseek" in base_url
        assert api_style == "openai"
        return ["deepseek-chat", "deepseek-reasoner"]

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    res = client.post("/api/agent/providers/list-models", json={"provider_id": "deepseek"})
    assert res.status_code == 200, res.text
    assert res.json()["models"] == ["deepseek-chat", "deepseek-reasoner"]
    assert "sk-list-test" not in res.text


def test_list_models_uses_draft_key_and_anthropic_style(client, monkeypatch):
    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        assert api_key == "sk-draft-ant"
        assert api_style == "anthropic"
        assert "anthropic" in base_url
        return ["claude-sonnet-4-5"]

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    res = client.post("/api/agent/providers/list-models", json={
        "provider_id": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_style": "anthropic",
        "api_key": "sk-draft-ant",
    })
    assert res.status_code == 200, res.text
    assert res.json()["models"] == ["claude-sonnet-4-5"]
    assert "sk-draft-ant" not in res.text


def test_list_models_does_not_send_stored_key_to_other_host(client, monkeypatch):
    client.put("/api/agent/settings", json={
        "chat_provider": "deepseek",
        "api_keys": {"deepseek": "sk-stored-secret"},
        "providers": [{
            "id": "deepseek",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model_ids": ["deepseek-chat"],
            "api_style": "openai",
        }],
    })
    seen = {}

    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return ["deepseek-chat"]

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    res = client.post("/api/agent/providers/list-models", json={
        "provider_id": "deepseek",
        "base_url": "https://attacker.example/collect",
    })
    assert res.status_code == 400
    assert seen == {}
    assert "sk-stored-secret" not in res.text
    assert "attacker.example" not in res.text

    masked = client.post("/api/agent/providers/list-models", json={
        "provider_id": "deepseek",
        "base_url": "https://api.openai.com",
        "api_key": "••••cret",
    })
    assert masked.status_code == 400
    assert seen == {}
    assert "sk-stored-secret" not in masked.text


def test_list_models_does_not_send_env_key_to_other_host(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-secret")
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-secret")
    seen = {}

    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return ["gpt-4o"]

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    res = client.post("/api/agent/providers/list-models", json={
        "provider_id": "deepseek",
        "base_url": "https://api.openai.com",
    })
    assert res.status_code == 400
    assert seen == {}
    assert "sk-env-secret" not in res.text
    assert "sk-loom-secret" not in res.text

    drafted = client.post("/api/agent/providers/list-models", json={
        "provider_id": "deepseek",
        "base_url": "https://api.openai.com",
        "api_key": "sk-draft-only",
    })
    assert drafted.status_code == 200, drafted.text
    assert seen["api_key"] == "sk-draft-only"
    assert seen["base_url"] == "https://api.openai.com"

    seen.clear()
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    saved = client.post("/api/agent/providers/list-models", json={"provider_id": "deepseek"})
    assert saved.status_code == 200, saved.text
    assert seen["api_key"] == "sk-env-secret"
    assert seen["base_url"] == "https://api.deepseek.com"
    assert "sk-env-secret" not in saved.text


def test_list_models_matching_url_still_uses_stored_key(client, monkeypatch):
    client.put("/api/agent/settings", json={
        "api_keys": {"deepseek": "sk-stored-secret"},
        "providers": [{
            "id": "deepseek",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model_ids": ["deepseek-chat"],
            "api_style": "openai",
        }],
    })
    seen = {}

    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return ["deepseek-chat"]

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    res = client.post("/api/agent/providers/list-models", json={
        "provider_id": "deepseek",
        "base_url": "https://API.DeepSeek.com/",
    })
    assert res.status_code == 200, res.text
    assert seen["api_key"] == "sk-stored-secret"
    assert seen["base_url"] == "https://api.deepseek.com"
    assert "sk-stored-secret" not in res.text


def test_list_models_hides_provider_error_body(client, monkeypatch):
    client.put("/api/agent/settings", json={
        "api_keys": {"deepseek": "sk-stored-secret"},
        "providers": [{
            "id": "deepseek",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model_ids": ["deepseek-chat"],
            "api_style": "openai",
        }],
    })

    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        raise LlmError("LLM HTTP 401: bearer sk-stored-secret echoed")

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    res = client.post("/api/agent/providers/list-models", json={"provider_id": "deepseek"})
    assert res.status_code == 400
    assert res.json()["detail"] == "Could not list models from the provider"
    assert "sk-stored-secret" not in res.text
    assert "echoed" not in res.text


def test_list_models_blocks_metadata_and_private_urls(client, monkeypatch):
    client.put("/api/agent/settings", json={
        "api_keys": {"custom-box": "sk-lan-secret", "deepseek": "sk-stored-secret"},
        "providers": [
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
                "api_style": "openai",
            },
            {
                "id": "custom-box",
                "name": "LAN",
                "base_url": "http://192.168.1.20:11434",
                "model_ids": ["qwen"],
                "api_style": "openai",
            },
        ],
    })
    seen = {}

    def fake_list(api_key, base_url, api_style="openai", timeout=30.0):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return ["qwen"]

    monkeypatch.setattr(api_module, "list_remote_models", fake_list)
    for body in (
        {"provider_id": "deepseek", "base_url": "http://169.254.169.254/latest/meta-data", "api_key": "sk-draft"},
        {"provider_id": "deepseek", "base_url": "http://10.1.2.3:11434", "api_key": "sk-draft"},
        {"provider_id": "deepseek", "base_url": "file:///etc/passwd", "api_key": "sk-draft"},
        {"provider_id": "deepseek", "base_url": "https://169.254.169.254", "api_key": "sk-draft"},
    ):
        res = client.post("/api/agent/providers/list-models", json=body)
        assert res.status_code == 400, body
        assert seen == {}
        assert "sk-stored-secret" not in res.text
        assert "169.254.169.254" not in res.text

    lan = client.post("/api/agent/providers/list-models", json={"provider_id": "custom-box"})
    assert lan.status_code == 200, lan.text
    assert seen["api_key"] == "sk-lan-secret"
    assert seen["base_url"] == "http://192.168.1.20:11434"

    loopback = client.post("/api/agent/providers/list-models", json={
        "provider_id": "deepseek",
        "base_url": "http://127.0.0.1:11434",
        "api_key": "sk-draft-local",
    })
    assert loopback.status_code == 200, loopback.text
    assert seen["api_key"] == "sk-draft-local"
    assert seen["base_url"] == "http://127.0.0.1:11434"


def test_removing_custom_chat_provider_persists(client):
    created = client.put("/api/agent/settings", json={
        "chat_provider": "custom-gone",
        "default_model": "llama-3",
        "providers": [
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
                "api_style": "openai",
            },
            {
                "id": "custom-gone",
                "name": "Temp",
                "base_url": "http://127.0.0.1:9",
                "model_ids": ["llama-3"],
                "api_style": "openai",
            },
        ],
        "api_keys": {"custom-gone": "sk-temp-9999"},
    })
    assert created.status_code == 200, created.text
    assert any(p["id"] == "custom-gone" for p in created.json()["providers"])
    assert created.json()["has_keys"]["custom-gone"] is True

    removed = client.put("/api/agent/settings", json={
        "chat_provider": "deepseek",
        "default_model": "deepseek-chat",
        "providers": [
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
                "api_style": "openai",
            },
        ],
    })
    assert removed.status_code == 200, removed.text
    ids = {p["id"] for p in removed.json()["providers"]}
    assert "custom-gone" not in ids
    assert removed.json()["has_keys"].get("custom-gone") is not True
    assert removed.json()["chat_provider"] == "deepseek"
    again = client.get("/api/agent/settings")
    assert "custom-gone" not in {p["id"] for p in again.json()["providers"]}
