"""API tests for Loom agent chat, suggest, accept, implement, settings."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import daemon.api as api_module
from daemon.graph_engine import GraphEngine
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


def test_settings_typesafe_and_clear(client):
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
