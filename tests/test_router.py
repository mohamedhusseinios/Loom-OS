"""Tests for the Router."""
import json
import pytest
from pathlib import Path
from daemon.registry import AgentRegistry
from daemon.graph_engine import GraphEngine
from daemon.recall import RecallEngine
from daemon.router import Router


@pytest.fixture
async def router_with_registry(tmp_path):
    db_path = tmp_path / "test.db"
    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    engine = GraphEngine()
    recall = RecallEngine(loom_dir=str(tmp_path))
    router = Router(reg, engine, recall=recall)
    yield router, reg, engine, tmp_path
    await reg.close()


@pytest.mark.asyncio
async def test_handle_register(router_with_registry):
    router, reg, engine, tmp_path = router_with_registry

    # Create a register.json
    inbox = tmp_path / "inbox" / "test-proj"
    inbox.mkdir(parents=True)
    register_file = inbox / "register.json"
    register_file.write_text(json.dumps({
        "agent": "test-agent",
        "version": "1.0",
        "project": "test-proj",
        "project_path": str(tmp_path / "fake-repo"),
        "capabilities": ["testing"],
    }))

    await router.handle_file("test-proj", str(register_file))

    # Agent should be registered
    agent = await reg.get_agent("test-agent-test-proj")
    assert agent is not None
    assert agent.agent_name == "test-agent"

    # Project should be created
    project = await reg.get_project("test-proj")
    assert project is not None


@pytest.mark.asyncio
async def test_handle_heartbeat(router_with_registry):
    router, reg, engine, tmp_path = router_with_registry

    # First register the agent
    from daemon.models import AgentInfo
    await reg.upsert_agent(AgentInfo(
        agent_id="test-agent-test-proj",
        agent_name="test-agent",
        version="1.0",
        project="test-proj",
        capabilities=["testing"],
    ))

    inbox = tmp_path / "inbox" / "test-proj"
    inbox.mkdir(parents=True)
    hb_file = inbox / "heartbeat.json"
    hb_file.write_text(json.dumps({
        "agent": "test-agent",
        "project": "test-proj",
        "status": "working hard",
        "timestamp": "2026-06-25T14:30:00Z",
    }))

    await router.handle_file("test-proj", str(hb_file))

    # Heartbeat should update
    agent = await reg.get_agent("test-agent-test-proj")
    assert agent is not None
    assert agent.status.value == "online"


@pytest.mark.asyncio
async def test_handle_unknown_file_ignored(router_with_registry):
    router, reg, engine, tmp_path = router_with_registry

    inbox = tmp_path / "inbox" / "test-proj"
    inbox.mkdir(parents=True)
    random_file = inbox / "random.txt"
    random_file.write_text("hello")

    # Should not raise
    await router.handle_file("test-proj", str(random_file))


@pytest.mark.asyncio
async def test_router_accepts_recall_engine(tmp_path):
    """Router can be constructed with an optional RecallEngine."""
    db_path = tmp_path / "test.db"
    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    engine = GraphEngine()
    recall = RecallEngine(loom_dir=str(tmp_path))

    router = Router(reg, engine, recall=recall)
    assert router.recall is recall
    await reg.close()


@pytest.mark.asyncio
async def test_recall_integration_preserves_existing_behavior(tmp_path):
    """Existing router behavior is intact after wiring RecallEngine."""
    db_path = tmp_path / "test.db"
    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    engine = GraphEngine()
    recall = RecallEngine(loom_dir=str(tmp_path))
    router = Router(reg, engine, recall=recall)

    inbox = tmp_path / "inbox" / "test-proj"
    inbox.mkdir(parents=True)
    register_file = inbox / "register.json"
    register_file.write_text(json.dumps({
        "agent": "test-agent",
        "version": "1.0",
        "project": "test-proj",
        "project_path": str(tmp_path / "fake-repo"),
        "capabilities": ["testing"],
    }))

    await router.handle_file("test-proj", str(register_file))

    agent = await reg.get_agent("test-agent-test-proj")
    assert agent is not None
    await reg.close()
