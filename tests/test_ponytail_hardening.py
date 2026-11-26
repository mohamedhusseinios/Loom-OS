"""Regression tests for ponytail-audit hardening (auth, binding, lease, MCP paths)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import daemon.api as api_module
from daemon.auth import configure_auth_token, verify_ws_token
from daemon.graph_engine import GraphEngine
from daemon.mcp_server import _project_inbox, _safe_project_id, add_to_memory
from daemon.models import AgentInfo, AgentSettingsUpdate, AgentTaskCreatePayload, AgentTaskStatus
from daemon.registry import AgentRegistry


@pytest.fixture
async def client(tmp_path):
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()
    await registry.upsert_project("noor", str(tmp_path / "noor"))
    await registry.upsert_agent(
        AgentInfo(
            agent_id="claude-code-noor",
            agent_name="claude-code",
            version="1.0",
            project="noor",
            capabilities=["code-analysis"],
        )
    )
    api_module.registry = registry
    api_module.graph_engine = GraphEngine()
    api_module.router = None
    api_module.watcher = None
    api_module.supervisor = None
    api_module.doc_ingestor = None
    api_module._federation_cache_key = None
    api_module.federation_index = None
    api_module.LOOM_INBOX_BASE = str(tmp_path / "inbox")
    with TestClient(api_module.app) as c:
        yield c
    await registry.close()


@pytest.fixture(autouse=True)
def _clear_auth():
    configure_auth_token(None)
    yield
    configure_auth_token(None)


def test_auth_blocks_api_gets_when_enabled(client):
    configure_auth_token("team-secret")
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/federated/stats").status_code == 401
    assert client.get("/api/health").status_code == 200
    ok = client.get("/api/projects", headers={"Authorization": "Bearer team-secret"})
    assert ok.status_code == 200


def test_ws_ticket_accepted_once(client):
    configure_auth_token("team-secret")
    res = client.post("/api/ws-ticket", headers={"Authorization": "Bearer team-secret"})
    assert res.status_code == 200
    ticket = res.json()["ticket"]
    assert ticket
    assert verify_ws_token(ticket) is True
    assert verify_ws_token(ticket) is False


@pytest.mark.asyncio
async def test_task_patch_rejects_wrong_project(client, tmp_path):
    registry = api_module.registry
    a = tmp_path / "alice"
    b = tmp_path / "bob"
    a.mkdir()
    b.mkdir()
    await registry.create_project("alice", "alice", str(a))
    await registry.create_project("bob", "bob", str(b))
    tid = await registry.create_agent_task(
        AgentTaskCreatePayload(
            project="alice", title="t", instruction="do it",
            assignee="claude-code-alice",
        ),
        status=AgentTaskStatus.READY,
    )
    res = client.patch(f"/api/projects/bob/tasks/{tid}", json={"status": "running"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_claim_is_exclusive(tmp_path):
    reg = AgentRegistry(str(tmp_path / "claim.db"))
    await reg.initialize()
    await reg.create_project("p", "p", str(tmp_path))
    tid = await reg.create_agent_task(
        AgentTaskCreatePayload(project="p", title="t", instruction="x"),
        status=AgentTaskStatus.RUNNING,
    )
    assert await reg.claim_task_execution(tid, "worker:a") is True
    assert await reg.claim_task_execution(tid, "worker:b") is False
    assert await reg.claim_task_execution(tid, "worker:a") is True
    await reg.close()


def test_mcp_rejects_path_traversal_project(tmp_path):
    with pytest.raises(ValueError):
        _safe_project_id("../etc")
    with pytest.raises(ValueError):
        _project_inbox("../../../tmp/pwn", loom_dir=str(tmp_path))
    bad = add_to_memory(
        finding="FOUND: leak", project="../../../tmp/pwn", agent="x", loom_dir=str(tmp_path),
    )
    assert "error" in bad
    ok = add_to_memory(
        finding="FOUND: ok", project="safe-proj", agent="x", loom_dir=str(tmp_path),
    )
    assert ok.get("status") == "stored"
    assert list((tmp_path / "inbox" / "safe-proj").glob("finding-*.md"))


@pytest.mark.asyncio
async def test_invalid_status_transition(client):
    registry = api_module.registry
    tid = await registry.create_agent_task(
        AgentTaskCreatePayload(project="noor", title="t", instruction="x"),
        status=AgentTaskStatus.DONE,
    )
    res = client.patch(f"/api/projects/noor/tasks/{tid}", json={"status": "running"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_credentials_encrypt_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOM_CREDENTIALS_KEY", "test-credentials-key")
    pytest.importorskip("cryptography")
    from daemon.credentials_crypto import decrypt_api_keys_json
    import aiosqlite

    db = tmp_path / "state.db"
    reg = AgentRegistry(str(db))
    await reg.initialize()
    assert oct(db.stat().st_mode)[-3:] == "600"
    await reg.update_agent_settings(AgentSettingsUpdate(api_keys={"deepseek": "sk-secret"}))
    async with aiosqlite.connect(str(db)) as conn:
        cur = await conn.execute("SELECT api_keys_json FROM agent_settings WHERE id = 1")
        row = await cur.fetchone()
        stored = row[0]
    assert stored.startswith("enc:v1:")
    assert "sk-secret" not in stored
    keys = await reg.get_raw_api_keys()
    assert keys.get("deepseek") == "sk-secret"
    assert json.loads(decrypt_api_keys_json(stored))["deepseek"] == "sk-secret"
    await reg.close()


@pytest.mark.asyncio
async def test_claim_rejects_non_running(tmp_path):
    reg = AgentRegistry(str(tmp_path / "claim2.db"))
    await reg.initialize()
    await reg.create_project("p", "p", str(tmp_path))
    tid = await reg.create_agent_task(
        AgentTaskCreatePayload(project="p", title="t", instruction="x"),
        status=AgentTaskStatus.TODO,
    )
    assert await reg.claim_task_execution(tid, "worker:a") is False
    await reg.update_agent_task(tid, status=AgentTaskStatus.RUNNING)
    assert await reg.claim_task_execution(tid, "worker:a") is True
    await reg.close()


@pytest.mark.asyncio
async def test_claim_api_rejects_non_running(client):
    registry = api_module.registry
    tid = await registry.create_agent_task(
        AgentTaskCreatePayload(project="noor", title="t", instruction="x"),
        status=AgentTaskStatus.READY,
    )
    res = client.post(f"/api/projects/noor/tasks/{tid}/claim", json={"owner": "worker:x"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_status_to_running_clears_poison_claim(client):
    registry = api_module.registry
    tid = await registry.create_agent_task(
        AgentTaskCreatePayload(
            project="noor", title="t", instruction="x",
            assignee="claude-code-noor",
        ),
        status=AgentTaskStatus.READY,
    )
    # Force a poison claim while still READY (bypass API status gate via SQL).
    await registry.db.execute(
        "UPDATE agent_tasks SET execution_owner = ? WHERE id = ?",
        ("evil", tid),
    )
    await registry.db.commit()
    res = client.patch(f"/api/projects/noor/tasks/{tid}", json={"status": "running"})
    assert res.status_code == 200
    row = await registry.get_agent_task(tid)
    # Lease cleared on status change; daemon may re-claim as daemon:<id>.
    assert row.execution_owner in (None, "", f"daemon:{tid}")


def test_inbox_helper_rejects_path_traversal(tmp_path):
    from fastapi import HTTPException

    api_module.LOOM_INBOX_BASE = str(tmp_path / "inbox")
    with pytest.raises(HTTPException) as exc:
        api_module._inbox_dir("../etc")
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        api_module._require_safe_project_id("a/b")
    assert exc.value.status_code == 400


def test_create_project_rejects_bad_name(client, tmp_path):
    d = tmp_path / "ok"
    d.mkdir()
    res = client.post("/api/projects", json={"name": "../evil", "path": str(d)})
    assert res.status_code == 400


def test_discover_rejects_outside_roots(client, monkeypatch, tmp_path):
    monkeypatch.delenv("LOOM_DISCOVER_ROOTS", raising=False)
    # /etc is outside home on typical setups
    res = client.get("/api/discover?path=/etc")
    assert res.status_code == 400


def test_encrypt_requires_cryptography_when_key_set(monkeypatch):
    monkeypatch.setenv("LOOM_CREDENTIALS_KEY", "k")
    import daemon.credentials_crypto as crypto
    monkeypatch.setattr(crypto, "_fernet", lambda material: None)
    with pytest.raises(RuntimeError, match="cryptography"):
        crypto.encrypt_api_keys_json("{}")

