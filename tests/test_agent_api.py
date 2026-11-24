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
from daemon.llm_client import LlmError
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


async def test_list_agent_chats_and_messages(client):
    """Sessions persist; list + transcript endpoints expose history."""
    import daemon.api as api_module

    c1 = await api_module.registry.create_agent_chat("noor", task_id=None)
    await api_module.registry.add_agent_message(c1.id, "user", "hello history")
    await api_module.registry.add_agent_message(c1.id, "assistant", "hi back")
    c2 = await api_module.registry.create_agent_chat("noor", task_id="task-1")
    await api_module.registry.add_agent_message(c2.id, "user", "task only")

    listed = client.get("/api/projects/noor/agent/chats")
    assert listed.status_code == 200
    body = listed.json()
    assert [c["id"] for c in body["chats"]] == [c1.id]
    assert body["chats"][0]["preview"] == "hi back"

    task_listed = client.get("/api/projects/noor/agent/chats", params={"task_id": "task-1"})
    assert [c["id"] for c in task_listed.json()["chats"]] == [c2.id]

    msgs = client.get(f"/api/projects/noor/agent/chats/{c1.id}/messages")
    assert msgs.status_code == 200
    contents = [m["content"] for m in msgs.json()["messages"]]
    assert contents == ["hello history", "hi back"]

    wrong_project = client.get(f"/api/projects/missing/agent/chats/{c1.id}/messages")
    assert wrong_project.status_code == 404

    missing_project = client.get("/api/projects/missing/agent/chats")
    assert missing_project.status_code == 404


async def test_archive_unarchive_delete_agent_chat(client):
    import daemon.api as api_module

    chat = await api_module.registry.create_agent_chat("noor", task_id=None)
    await api_module.registry.add_agent_message(chat.id, "user", "secret")

    arch = client.post(f"/api/projects/noor/agent/chats/{chat.id}/archive")
    assert arch.status_code == 200
    assert arch.json()["archived_at"] is not None
    assert arch.json()["id"] == chat.id

    # idempotent
    arch2 = client.post(f"/api/projects/noor/agent/chats/{chat.id}/archive")
    assert arch2.status_code == 200
    assert arch2.json()["archived_at"] == arch.json()["archived_at"]

    active = client.get("/api/projects/noor/agent/chats")
    assert chat.id not in [c["id"] for c in active.json()["chats"]]

    archived = client.get("/api/projects/noor/agent/chats", params={"archived": 1})
    assert [c["id"] for c in archived.json()["chats"]] == [chat.id]

    un = client.post(f"/api/projects/noor/agent/chats/{chat.id}/unarchive")
    assert un.status_code == 200
    assert un.json()["archived_at"] is None
    assert chat.id in [c["id"] for c in client.get("/api/projects/noor/agent/chats").json()["chats"]]

    wrong = client.post(f"/api/projects/missing/agent/chats/{chat.id}/archive")
    assert wrong.status_code == 404

    deleted = client.delete(f"/api/projects/noor/agent/chats/{chat.id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/noor/agent/chats/{chat.id}/messages").status_code == 404
    assert client.delete(f"/api/projects/noor/agent/chats/{chat.id}").status_code == 404


def test_chat_without_key_returns_400(client):

    res = client.post("/api/projects/noor/agent/chat", json={"message": "hi"})
    assert res.status_code == 400
    assert "API key" in res.json()["detail"]


def test_keyless_custom_chat_does_not_send_loom_env_key(client, monkeypatch):
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-secret")
    saved = client.put("/api/agent/settings", json={
        "default_model": "llama-3.1-8b",
        "chat_provider": "local-llm",
        "providers": [{
            "id": "local-llm",
            "name": "Local",
            "base_url": "http://127.0.0.1:9000/v1",
            "model_ids": ["llama-3.1-8b"],
            "api_style": "openai",
            "kind": "openai_compatible",
        }],
    })
    assert saved.status_code == 200, saved.text
    captured = {}

    class _Resp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello local"}}], "usage": {}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    res = client.post("/api/projects/noor/agent/chat", json={"message": "hi"})
    assert res.status_code == 200, res.text
    assert res.json()["reply"] == "hello local"
    assert captured["auth"] is None
    assert "127.0.0.1:9000" in captured["url"]
    assert "sk-loom-secret" not in res.text


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
    assert manifest["test_command"] == ["python", "-m", "pytest", "-q"]
    assert manifest["lint_command"] == ["python", "-m", "ruff", "check", "."]
    assert "LOOM_AGENT_MANIFEST" not in os.environ


@pytest.mark.asyncio
async def test_implement_manifest_includes_acceptance_criteria(client):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Ship loop", instruction="add the cancel flag",
        acceptance_criteria="flag file exists",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["prompt"] == "add the cancel flag\n\nAcceptance criteria:\nflag file exists"


@pytest.mark.asyncio
async def test_exited_worker_seals_run_failed(client):
    from daemon.supervisor import WorkerSupervisor

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Die early", instruction="never finishes",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        created = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert created.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    supervisor = WorkerSupervisor()
    supervisor._exited.add(tid)
    api_module.supervisor = supervisor
    try:
        sealed = await agent_runtime_module.seal_exited_worker_runs(
            reg, supervisor, None, JsonlEventTail(),
        )
    finally:
        api_module.supervisor = None
    assert sealed == 1
    updated = await reg.get_agent_run(run.id)
    assert updated.status == "failed"
    assert updated.stop_reason == "worker_exit"
    last = json.loads((Path(run.run_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last == {"type": "run.failed", "stop_reason": "worker_exit"}


@pytest.mark.asyncio
async def test_respawned_worker_is_not_sealed_failed(client, monkeypatch):
    import daemon.supervisor as sup_mod
    from daemon.supervisor import WorkerSupervisor

    class _LiveProc:
        def __init__(self, cmd, *args, **kwargs):
            self._returncode = None
        def poll(self):
            return self._returncode

    monkeypatch.setattr(sup_mod.subprocess, "Popen", _LiveProc)
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Retry me", instruction="try again",
    ))
    with patch.object(api_module, "_route_task_execution", return_value=True):
        created = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert created.status_code == 200
    first = (await reg.list_agent_runs(task_id=tid))[0]
    supervisor = WorkerSupervisor()
    supervisor.spawn("noor", "loom-agent", "/tmp/noor", tid)
    supervisor._procs[tid]._returncode = 1
    assert tid in supervisor.exited_task_ids()
    await reg.create_agent_run(
        task_id=tid, project="noor", run_dir=first.run_dir + "-retry", status="running",
    )
    supervisor.spawn("noor", "loom-agent", "/tmp/noor", tid)
    assert supervisor.is_running(tid) is True
    sealed = await agent_runtime_module.seal_exited_worker_runs(
        reg, supervisor, None, JsonlEventTail(),
    )
    assert sealed == 0
    runs = await reg.list_agent_runs(task_id=tid)
    assert {run.status for run in runs} == {"running"}


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


def test_autonomy_settings_defaults_update_and_validate(client):
    initial = client.get("/api/agent/settings")
    assert initial.status_code == 200
    assert initial.json()["selection_autonomy_enabled"] is True
    assert initial.json()["autonomy_min_fit"] == "High"
    assert initial.json()["autonomy_require_margin"] is True

    updated = client.put("/api/agent/settings", json={
        "selection_autonomy_enabled": False,
        "autonomy_min_fit": "Medium",
        "autonomy_require_margin": False,
    })
    assert updated.status_code == 200
    assert updated.json()["selection_autonomy_enabled"] is False
    assert updated.json()["autonomy_min_fit"] == "Medium"
    assert updated.json()["autonomy_require_margin"] is False

    invalid = client.put("/api/agent/settings", json={"autonomy_min_fit": "medium"})
    assert invalid.status_code == 400
    assert "autonomy_min_fit" in invalid.json()["detail"]
    kept = client.get("/api/agent/settings")
    assert kept.json()["autonomy_min_fit"] == "Medium"



def test_openrouter_jev_decision_provider_accepted(client):
    res = client.put(
        "/api/agent/settings",
        json={
            "filter_provider": "openrouter_jev",
            "judgment_provider": "openrouter_jev",
            "api_keys": {"openrouter_jev": "sk-or-test9999"},
            "providers": [{
                "id": "openrouter_jev",
                "name": "Jev (OpenRouter)",
                "base_url": "https://openrouter.ai/api",
                "model_ids": ["~typesafe/jev-latest"],
            }],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["filter_provider"] == "openrouter_jev"
    assert body["judgment_provider"] == "openrouter_jev"
    assert body["has_keys"]["openrouter_jev"] is True
    assert body["api_keys_masked"]["openrouter_jev"] == "••••9999"
    row = next(p for p in body["providers"] if p["id"] == "openrouter_jev")
    assert row["base_url"] == "https://openrouter.ai/api"
    assert row["model_ids"] == ["~typesafe/jev-latest"]


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


_SEL_STAGE1 = {"type:bugfix": 0.9, "size:small": 0.8, "risk:low": 0.7, "has_tests:yes": 0.9, "repo_familiarity:high": 0.6}
_SEL_DECIDABLE = {"debug": 0.9, "tdd": 0.4, "react": 0.3, "plan_then_execute": 0.2, "review_only": 0.1}
_SEL_AMBIGUOUS = {"debug": 0.9, "tdd": 0.85, "react": 0.3, "plan_then_execute": 0.2, "review_only": 0.1}


class _SelClient:
    def __init__(self, scores, skipped=False):
        self.scores, self.skipped = scores, skipped

    def filter_relevance(self, **kwargs):
        raise AssertionError("unused")

    def judge(self, *, pack, **kwargs):
        from daemon.decision import DecisionResult
        scores = _SEL_STAGE1 if pack == "pattern_stage1" else self.scores
        return DecisionResult(scores=dict(scores), provider="fake", model="m", skipped=self.skipped, skip_reason="none" if self.skipped else None)


def _patch_selection(scores=None, skipped=False):
    stage1 = _SelClient(_SEL_STAGE1, skipped)
    stage2 = _SelClient(scores or _SEL_DECIDABLE, skipped)
    return patch.object(agent_runtime_module.AgentRuntime, "_selection_clients", lambda self, settings, raw_keys: (stage1, stage2))


async def _new_task(reg):
    return await reg.create_agent_task(AgentTaskCreatePayload(project="noor", title="Sel", instruction="fix login bug"))


@pytest.mark.asyncio
async def test_implement_preview_shape_and_stateless(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection():
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement/preview")
    assert res.status_code == 200
    body = res.json()
    assert body["recommended"]["family_id"] == "debug"
    assert body["auto_decidable"] is True
    assert [r["family_id"] for r in body["top3"]][0] == "debug"
    assert len(body["top3"]) == 3
    assert body["fallback"] is False
    assert await reg.list_agent_runs(task_id=tid) == []
    assert (await reg.get_agent_task(tid)).status == AgentTaskStatus.TODO


@pytest.mark.asyncio
async def test_implement_preview_unknown_task_404(client):
    assert client.post("/api/projects/noor/tasks/nope/implement/preview").status_code == 404


@pytest.mark.asyncio
async def test_implement_user_pick_locks_family(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": "tdd", "modifier_ids": ["m1"], "recommended_family_id": "debug"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "tdd"
    assert json.loads(run.modifier_ids_json) == ["m1"]
    assert run.chosen_source == "user"
    assert run.user_override is True
    assert json.loads(run.recommended_json)["family_id"] == "debug"
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["family_id"] == "tdd"
    assert manifest["modifier_ids"] == ["m1"]
    assert manifest["runner_fallback"] is True


@pytest.mark.asyncio
async def test_implement_user_pick_matching_recommendation_not_override(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": "debug", "recommended_family_id": "debug"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.user_override is False


@pytest.mark.asyncio
async def test_implement_user_pick_react_no_runner_fallback(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": "react"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runner_fallback"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"choice": "user"}, {"choice": "user", "family_id": "orchestrator_workers"}, {"choice": "user", "family_id": "nope"}])
async def test_implement_user_pick_invalid_family_400(client, body):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection():
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json=body)
    assert res.status_code == 400
    assert await reg.list_agent_runs(task_id=tid) == []
    assert (await reg.get_agent_task(tid)).status == AgentTaskStatus.TODO


@pytest.mark.asyncio
async def test_implement_auto_409_when_not_decidable(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(_SEL_AMBIGUOUS):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "auto"})
    assert res.status_code == 409
    assert res.json()["auto_decidable"] is False
    assert res.json()["recommended"]["family_id"] == "debug"
    assert await reg.list_agent_runs(task_id=tid) == []
    assert (await reg.get_agent_task(tid)).status == AgentTaskStatus.TODO


@pytest.mark.asyncio
async def test_implement_auto_not_decidable_autonomy_disabled_proceeds(client):
    reg = api_module.registry
    from daemon.models import AgentSettingsUpdate
    await reg.update_agent_settings(AgentSettingsUpdate(selection_autonomy_enabled=False))
    tid = await _new_task(reg)
    with _patch_selection(_SEL_AMBIGUOUS), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "auto"})
    assert res.status_code == 200
    assert (await reg.list_agent_runs(task_id=tid))[0].family_id == "debug"


@pytest.mark.asyncio
async def test_implement_auto_success_locks_recommended(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "auto"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "debug"
    assert run.chosen_source == "auto"
    assert run.user_override is False
    assert run.selection_filter_provider == "fake"
    assert json.loads(run.selection_scores_json)["debug"] == 0.9
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runner_fallback"] is True


@pytest.mark.asyncio
async def test_implement_empty_body_compat(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement")
    assert res.status_code == 200
    assert (await reg.list_agent_runs(task_id=tid))[0].family_id == "debug"


@pytest.mark.asyncio
async def test_implement_fallback_default_when_clients_skip(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(skipped=True), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "auto"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "react"
    assert run.chosen_source == "fallback_default"
    assert run.selection_skip_reason
    manifest = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runner_fallback"] is False


@pytest.mark.asyncio
async def test_implement_cross_project_task_404(client):
    reg = api_module.registry
    await reg.upsert_project("other", "/tmp/other-project")
    tid = await reg.create_agent_task(AgentTaskCreatePayload(project="other", title="Theirs", instruction="not yours"))
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "auto"})
        prev = client.post(f"/api/projects/noor/tasks/{tid}/implement/preview")
    assert res.status_code == 404
    assert prev.status_code == 404
    assert await reg.list_agent_runs(task_id=tid) == []
    assert (await reg.get_agent_task(tid)).status == AgentTaskStatus.TODO


@pytest.mark.asyncio
async def test_implement_settings_failure_falls_back_to_react(client):
    reg = api_module.registry
    tid = await _new_task(reg)

    async def boom(self):
        raise RuntimeError("settings unavailable")

    with patch.object(agent_runtime_module.AgentRuntime, "_decision_settings", boom), patch.object(api_module, "_route_task_execution", return_value=True):
        prev = client.post(f"/api/projects/noor/tasks/{tid}/implement/preview")
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "auto"})
    assert prev.status_code == 200
    assert prev.json()["fallback"] is True
    assert prev.json()["recommended"]["family_id"] == "react"
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "react"
    assert run.chosen_source == "fallback_default"


@pytest.mark.asyncio
async def test_implement_pattern_load_failure_falls_back_to_react(client):
    reg = api_module.registry
    tid = await _new_task(reg)

    def boom(directory):
        raise RuntimeError("bad families dir")

    with patch.object(agent_runtime_module, "load_patterns", boom), patch.object(api_module, "_route_task_execution", return_value=True):
        prev = client.post(f"/api/projects/noor/tasks/{tid}/implement/preview")
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": "tdd"})
    assert prev.status_code == 200
    assert prev.json()["fallback"] is True
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "react"
    assert run.chosen_source == "fallback_default"


@pytest.mark.asyncio
async def test_implement_runner_fallback_derives_from_runner_key(client, tmp_path):
    import coding_agent.patterns as patterns_pkg
    src = (Path(patterns_pkg.__file__).parent / "families" / "react.yaml").read_text(encoding="utf-8")
    fam_dir = tmp_path / "families"
    fam_dir.mkdir()
    (fam_dir / "react.yaml").write_text(src, encoding="utf-8")
    alias = src.replace("id: react\n", "id: react_alias\n", 1)
    assert "id: react_alias" in alias and "runner: react" in alias
    (fam_dir / "react_alias.yaml").write_text(alias, encoding="utf-8")
    norunner = src.replace("id: react\n", "id: norunner\n", 1).replace("runner: react\n", "")
    assert "runner:" not in norunner
    (fam_dir / "norunner.yaml").write_text(norunner, encoding="utf-8")
    reg = api_module.registry
    results = {}
    for fam in ("react_alias", "norunner"):
        tid = await _new_task(reg)
        with _patch_selection(), patch.object(agent_runtime_module, "FAMILIES_DIR", fam_dir), patch.object(api_module, "_route_task_execution", return_value=True):
            res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": fam})
        assert res.status_code == 200
        run = (await reg.list_agent_runs(task_id=tid))[0]
        assert run.family_id == fam
        results[fam] = json.loads((Path(run.run_dir) / "manifest.json").read_text(encoding="utf-8"))["runner_fallback"]
    assert results == {"react_alias": False, "norunner": True}


@pytest.mark.asyncio
async def test_implement_user_pick_does_not_rescore(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    stage1 = _SelClient(_SEL_STAGE1, False)
    stage2 = _SelClient(_SEL_DECIDABLE, False)
    calls = []
    orig = _SelClient.judge

    def counting(self, *, pack, **kwargs):
        calls.append(pack)
        return orig(self, pack=pack, **kwargs)

    with patch.object(_SelClient, "judge", counting), patch.object(agent_runtime_module.AgentRuntime, "_selection_clients", lambda self, settings, raw_keys: (stage1, stage2)), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": "tdd", "recommended_family_id": "debug"})
    assert res.status_code == 200
    assert calls == []
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "tdd" and run.user_override is True
    assert json.loads(run.recommended_json)["family_id"] == "debug"


@pytest.mark.asyncio
async def test_implement_user_pick_without_recommended_not_override(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "user", "family_id": "tdd"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.user_override is False
    assert run.recommended_json is None


@pytest.mark.asyncio
async def test_implement_delegate_never_409_when_not_decidable(client):
    reg = api_module.registry
    tid = await _new_task(reg)
    with _patch_selection(_SEL_AMBIGUOUS), patch.object(api_module, "_route_task_execution", return_value=True):
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement", json={"choice": "delegate"})
    assert res.status_code == 200
    run = (await reg.list_agent_runs(task_id=tid))[0]
    assert run.family_id == "debug"
    assert run.chosen_source == "auto"
    assert run.user_override is False


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


@pytest.mark.asyncio
async def test_implement_open_run_failure_keeps_prior_status(client, monkeypatch):
    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Fail open", instruction="do it",
    ))
    await reg.update_agent_task(tid, status=AgentTaskStatus.READY)
    runtime = api_module._get_agent_runtime()
    with patch.object(runtime, "_open_coding_run", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            await runtime.implement("noor", tid, spawn_worker=None)
    task = await reg.get_agent_task(tid)
    assert task.status == AgentTaskStatus.READY
    assert await reg.list_agent_runs(task_id=tid) == []


@pytest.mark.asyncio
async def test_implement_rejects_live_worker(client):
    import daemon.supervisor as sup_mod
    from daemon.agent_runtime import ConflictError

    reg = api_module.registry
    tid = await reg.create_agent_task(AgentTaskCreatePayload(
        project="noor", title="Busy", instruction="do it",
    ))
    await reg.update_agent_task(tid, status=AgentTaskStatus.READY)
    api_module.supervisor = sup_mod.WorkerSupervisor()
    proc = MagicMock()
    proc.poll.return_value = None
    api_module.supervisor._procs[tid] = proc
    try:
        res = client.post(f"/api/projects/noor/tasks/{tid}/implement")
        assert res.status_code == 409
        assert "worker" in res.json()["detail"].lower()
        task = await reg.get_agent_task(tid)
        assert task.status == AgentTaskStatus.READY
        assert await reg.list_agent_runs(task_id=tid) == []
        runtime = api_module._get_agent_runtime()
        with pytest.raises(ConflictError):
            await runtime.implement("noor", tid, worker_live=lambda _tid: True)
    finally:
        api_module.supervisor = None


_OPENROUTER = {
    "id": "openrouter", "name": "OpenRouter",
    "base_url": "https://openrouter.ai/api/v1",
    "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible",
}


def test_keyless_custom_chat_posts_single_v1(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-secret")
    saved = client.put("/api/agent/settings", json={
        "default_model": "llama-3.1-8b",
        "chat_provider": "openrouter",
        "providers": [_OPENROUTER],
    })
    assert saved.status_code == 200
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "hello local"}}], "usage": {}}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("daemon.llm_client._open_http", side_effect=fake_urlopen):
        chat = client.post("/api/projects/noor/agent/chat", json={"message": "hi"})
    assert chat.status_code == 200
    assert chat.json()["reply"] == "hello local"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["auth"] is None


def test_put_settings_accepts_custom_openai_compatible_provider(client):
    resp = client.put("/api/agent/settings", json={
        "default_model": "llama-3.1-8b",
        "filter_provider": "openrouter",
        "judgment_provider": "openrouter",
        "providers": [_OPENROUTER],
        "api_keys": {"openrouter": "sk-or"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["filter_provider"] == "openrouter"
    assert body["judgment_provider"] == "openrouter"
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


@pytest.mark.parametrize("bad_id", ["none", "Bad Id", "x", "has.dot"])
def test_put_settings_rejects_invalid_custom_provider_id(client, bad_id):
    resp = client.put("/api/agent/settings", json={
        "providers": [{**_OPENROUTER, "id": bad_id}],
    })
    assert resp.status_code == 400


@pytest.mark.parametrize("override", [{"base_url": "  "}, {"model_ids": []}, {"model_ids": ["  "]}])
def test_put_settings_rejects_custom_provider_missing_base_url_or_model(client, override):
    resp = client.put("/api/agent/settings", json={"providers": [{**_OPENROUTER, **override}]})
    assert resp.status_code == 400


def test_put_settings_custom_judgment_gliclass_still_rejected(client):
    resp = client.put("/api/agent/settings", json={
        "judgment_provider": "gliclass", "providers": [_OPENROUTER],
    })
    assert resp.status_code == 400
    assert "gliclass" in resp.json()["detail"]


def test_put_settings_rejects_unknown_custom_role(client):
    resp = client.put("/api/agent/settings", json={"filter_provider": "openrouter"})
    assert resp.status_code == 400


def test_put_settings_remove_provider_ids_blocked_when_in_use(client):
    seeded = client.put("/api/agent/settings", json={
        "filter_provider": "openrouter",
        "judgment_provider": "none",
        "providers": [_OPENROUTER],
    })
    assert seeded.status_code == 200
    blocked = client.put("/api/agent/settings", json={"remove_provider_ids": ["openrouter"]})
    assert blocked.status_code == 400
    assert "openrouter" in blocked.json()["detail"]
    still = client.get("/api/agent/settings").json()
    assert any(p["id"] == "openrouter" for p in still["providers"])
    assert still["filter_provider"] == "openrouter"
    client.put("/api/agent/settings", json={"filter_provider": "none", "judgment_provider": "none", "default_model": "deepseek-chat"})
    ok = client.put("/api/agent/settings", json={"remove_provider_ids": ["openrouter"]})
    assert ok.status_code == 200
    assert all(p["id"] != "openrouter" for p in ok.json()["providers"])


def test_put_settings_remove_provider_blocked_when_default_model_uses_it(client):
    client.put("/api/agent/settings", json={"default_model": "llama-3.1-8b", "providers": [_OPENROUTER]})
    blocked = client.put("/api/agent/settings", json={"remove_provider_ids": ["openrouter"]})
    assert blocked.status_code == 400
    assert "openrouter" in blocked.json()["detail"]


def test_put_settings_remove_builtin_provider_rejected(client):
    resp = client.put("/api/agent/settings", json={"remove_provider_ids": ["deepseek"]})
    assert resp.status_code == 400


def test_put_settings_remove_provider_drops_its_api_key(client):
    client.put("/api/agent/settings", json={"providers": [_OPENROUTER], "api_keys": {"openrouter": "sk-or"}})
    ok = client.put("/api/agent/settings", json={"remove_provider_ids": ["openrouter"]})
    assert ok.status_code == 200
    assert not ok.json()["has_keys"].get("openrouter")


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


def _configure_keyless_local_chat(client):
    saved = client.put("/api/agent/settings", json={
        "default_model": "llama-3.1-8b",
        "chat_provider": "local-llm",
        "providers": [{
            "id": "local-llm",
            "name": "Local",
            "base_url": "http://127.0.0.1:9000/v1",
            "model_ids": ["llama-3.1-8b"],
            "api_style": "openai",
            "kind": "openai_compatible",
        }],
    })
    assert saved.status_code == 200, saved.text


async def test_agent_chat_stream_sse(client, monkeypatch, tmp_path):
    _configure_keyless_local_chat(client)
    graph_dir = tmp_path / "noor" / "graphify-out"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(json.dumps({"nodes": [], "links": []}))
    chunks = [
        b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"b"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    class _StreamResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter(chunks)

    monkeypatch.setattr("daemon.llm_client._open_http", lambda req, timeout=120.0: _StreamResp())

    with client.stream("POST", "/api/projects/noor/agent/chat/stream", json={"message": "hi"}) as res:
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")
        body = "".join(res.iter_text())
    assert "event: meta" in body
    assert "event: reasoning_delta" in body
    assert "event: content_delta" in body
    assert "event: done" in body
    done = [b for b in body.split("\n\n") if b.startswith("event: done")][0]
    data = json.loads(done.split("data: ", 1)[1])
    assert data["reply"] == "ab"
    assert data["reasoning"] == "think"

    msgs = client.get(f"/api/projects/noor/agent/chats/{data['chat_id']}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("assistant", "ab")]


def test_agent_chat_stream_missing_project_404(client):
    res = client.post("/api/projects/missing/agent/chat/stream", json={"message": "hi"})
    assert res.status_code == 404


def test_agent_chat_stream_without_key_returns_400(client):
    res = client.post("/api/projects/noor/agent/chat/stream", json={"message": "hi"})
    assert res.status_code == 400
    assert "API key" in res.json()["detail"]


async def test_agent_chat_stream_persists_partial_on_error(client, monkeypatch, tmp_path):
    _configure_keyless_local_chat(client)
    graph_dir = tmp_path / "noor" / "graphify-out"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(json.dumps({"nodes": [], "links": []}))

    class _BrokenResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"part"}}]}\n\n'
            raise OSError("connection reset")

    monkeypatch.setattr("daemon.llm_client._open_http", lambda req, timeout=120.0: _BrokenResp())

    with client.stream("POST", "/api/projects/noor/agent/chat/stream", json={"message": "hi"}) as res:
        body = "".join(res.iter_text())
    assert "event: error" in body
    assert "connection reset" in body
    meta = [b for b in body.split("\n\n") if b.startswith("event: meta")][0]
    chat_id = json.loads(meta.split("data: ", 1)[1])["chat_id"]
    msgs = client.get(f"/api/projects/noor/agent/chats/{chat_id}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("assistant", "part")]


async def test_agent_chat_stream_task_chat_one_shot(client):
    _configure_keyless_local_chat(client)
    tid = await api_module.registry.create_agent_task(AgentTaskCreatePayload(
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
    with patch("daemon.agent_runtime.Orchestrator.run_suggest_cycle", return_value=fake):
        with client.stream("POST", "/api/projects/noor/agent/chat/stream", json={"message": "hi", "task_id": tid}) as res:
            body = "".join(res.iter_text())
    events = [b.split("\n", 1)[0] for b in body.strip().split("\n\n")]
    assert events == ["event: meta", "event: content_delta", "event: done"]
    done = json.loads(body.strip().split("\n\n")[-1].split("data: ", 1)[1])
    assert done["reply"] == "Promote to ready"
    assert done["suggestion_id"]
    msgs = client.get(f"/api/projects/noor/agent/chats/{done['chat_id']}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
