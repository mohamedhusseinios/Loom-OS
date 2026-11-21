"""API tests for Loom agent chat, suggest, accept, implement, settings."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import daemon.api as api_module
import daemon.agent_runtime as agent_runtime_module
from daemon.agent_runtime import JsonlEventTail, drain_run_jsonl, emit_new_run_events
from daemon.graph_engine import GraphEngine
from daemon.models import AgentInfo, AgentTaskCreatePayload, AgentTaskStatus
from daemon.orchestrator import SuggestResult
from daemon.registry import AgentRegistry


@pytest.fixture
async def client(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        agent_runtime_module, "loom_run_dir",
        lambda run_id: tmp_path / ".loom" / "runs" / run_id,
        raising=False,
    )
    monkeypatch.delenv("LOOM_AGENT_MANIFEST", raising=False)
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
async def test_implement_creates_run_row_and_manifest(client, tmp_path):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Ship loop", instruction="add the cancel flag",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert res.status_code == 200
    runs = await reg.list_agent_runs(task_id=tid)
    assert len(runs) == 1
    run = runs[0]
    assert run.project == "noor"
    assert run.family_id == "react"
    assert run.modifier_ids_json == "[]"
    assert run.status == "running"
    assert run.step_limit == 40
    assert run.token_limit == 100000
    assert run.cost_limit == 1.0
    assert run.steps_used == 0
    run_dir = Path(run.run_dir)
    assert run_dir == tmp_path / ".loom" / "runs" / run.id
    manifest_path = run_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["family_id"] == "react"
    assert manifest["step_limit"] == 40
    assert manifest["token_limit"] == 100000
    assert manifest["cost_limit"] == 1.0
    assert manifest["cost_limit_usd"] == 1.0
    assert manifest["prompt"] == "add the cancel flag"
    assert manifest["run_dir"] == str(run_dir)
    assert manifest["cancel_path"] == str(run_dir / "cancel")
    assert manifest["events_path"] == str(run_dir / "events.jsonl")
    assert "LOOM_AGENT_MANIFEST" not in os.environ


@pytest.mark.asyncio
async def test_cancel_run_writes_cancel_file(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Stop me", instruction="loop until cancelled",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        created = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert created.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    res = client.post(f"/api/projects/noor/runs/{run.id}/cancel")
    assert res.status_code == 200
    assert (Path(run.run_dir) / "cancel").is_file()
    updated = await reg.get_agent_run(run.id)
    assert updated.status == "cancelling"
    missing = client.post("/api/projects/noor/runs/missing-run/cancel")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_implements_pass_distinct_manifest_env(client, monkeypatch):
    import daemon.supervisor as sup_mod

    captured = []

    def _factory(cmd, *args, **kwargs):
        captured.append(kwargs.get("env"))
        proc = MagicMock()
        proc.poll.return_value = None
        return proc

    monkeypatch.setattr(sup_mod.subprocess, "Popen", _factory)
    monkeypatch.setenv("LOOM_AGENT_MANIFEST", "/tmp/stale-manifest.json")
    api_module.supervisor = sup_mod.WorkerSupervisor()
    try:
        reg = api_module.registry
        task_ids = []
        for title in ("one", "two"):
            task_ids.append(await reg.create_agent_task(AgentTaskCreatePayload(
                project="noor", title=title, instruction=f"do {title}",
            )))
        runtime = api_module._get_agent_runtime()

        async def go(task_id):
            updated, manifest_path = await runtime.implement("noor", task_id)
            await api_module._route_task_execution("noor", updated, manifest_path=manifest_path)
            return manifest_path

        paths = await asyncio.gather(go(task_ids[0]), go(task_ids[1]))
    finally:
        api_module.supervisor = None
    assert "LOOM_AGENT_MANIFEST" not in os.environ
    assert paths[0] != paths[1]
    spawned = [env["LOOM_AGENT_MANIFEST"] for env in captured]
    assert sorted(spawned) == sorted(paths)
    assert "/tmp/stale-manifest.json" not in spawned
    assert all(Path(path).is_file() for path in spawned)


@pytest.mark.asyncio
async def test_cancel_emits_pending_jsonl_and_later_terminal_event(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Stop late", instruction="loop until cancelled",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        created = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert created.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    events_path = Path(run.run_dir) / "events.jsonl"
    events_path.write_text('{"type": "step", "n": 1}\n', encoding="utf-8")
    seen = []

    async def emit(event, project, data):
        seen.append((event, project, data))

    api_module._get_agent_runtime().emit_event = emit
    res = client.post(f"/api/projects/noor/runs/{run.id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelling"
    assert seen == [(
        "agent:run_event", "noor",
        {"run_id": run.id, "task_id": tid, "payload": {"type": "step", "n": 1}},
    )]
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "run.cancelled", "stop_reason": "cancelled"}\n')
    fresh = await reg.get_agent_run(run.id)
    await drain_run_jsonl(fresh, api_module._run_event_tail, emit, reg)
    assert seen[-1][2]["payload"]["type"] == "run.cancelled"
    updated = await reg.get_agent_run(run.id)
    assert updated.status == "cancelled"
    assert updated.stop_reason == "cancelled"


@pytest.mark.asyncio
async def test_drain_terminal_event_marks_run_succeeded(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Finish", instruction="finish the run",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        created = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert created.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    (Path(run.run_dir) / "events.jsonl").write_text(
        '{"type": "run.succeeded", "stop_reason": "done"}\n', encoding="utf-8",
    )
    seen = []

    async def emit(event, project, data):
        seen.append(data["payload"]["type"])

    await drain_run_jsonl(run, JsonlEventTail(), emit, reg)
    assert seen == ["run.succeeded"]
    updated = await reg.get_agent_run(run.id)
    assert updated.status == "succeeded"
    assert updated.stop_reason == "done"


def test_jsonl_tail_reads_only_new_complete_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    tail = JsonlEventTail()
    assert tail.poll(path) == []
    path.write_text('{"type": "step"}\n{"type": "partial"', encoding="utf-8")
    assert tail.poll(path) == [{"type": "step"}]
    assert tail.poll(path) == []
    with path.open("a", encoding="utf-8") as handle:
        handle.write('}\n')
    assert tail.poll(path) == [{"type": "partial"}]


@pytest.mark.asyncio
async def test_jsonl_tail_emits_agent_run_event(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"type": "run.succeeded", "stop_reason": "done"}\n', encoding="utf-8")
    seen = []

    async def emit(event, project, data):
        seen.append((event, project, data))

    tail = JsonlEventTail()
    count = await emit_new_run_events(path, tail, emit, "noor", "run-1", "task-1")
    assert count == 1
    assert seen == [(
        "agent:run_event",
        "noor",
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "payload": {"type": "run.succeeded", "stop_reason": "done"},
        },
    )]
    assert await emit_new_run_events(path, tail, emit, "noor", "run-1", "task-1") == 0


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
