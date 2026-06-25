"""Tests for the Agent Registry."""
import pytest
from daemon.registry import AgentRegistry
from daemon.models import AgentInfo, AgentStatus


@pytest.fixture
async def registry(tmp_path):
    db_path = tmp_path / "test.db"
    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    yield reg
    await reg.close()


@pytest.mark.asyncio
async def test_register_agent(registry):
    agent = AgentInfo(
        agent_id="claude-code-noor",
        agent_name="claude-code",
        version="2.1.190",
        project="noor",
        capabilities=["code-analysis", "refactoring"],
    )
    await registry.upsert_agent(agent)
    result = await registry.get_agent("claude-code-noor")
    assert result is not None
    assert result.agent_name == "claude-code"
    assert result.project == "noor"


@pytest.mark.asyncio
async def test_upsert_project(registry):
    await registry.upsert_project("noor", "/tmp/noor")
    project = await registry.get_project("noor")
    assert project is not None
    assert project.project_path == "/tmp/noor"


@pytest.mark.asyncio
async def test_list_projects(registry):
    await registry.upsert_project("noor", "/tmp/noor")
    await registry.upsert_project("mailo", "/tmp/mailo")
    projects = await registry.list_projects()
    assert len(projects) == 2


@pytest.mark.asyncio
async def test_list_agents_by_project(registry):
    await registry.upsert_agent(AgentInfo(
        agent_id="cc-noor", agent_name="claude-code", version="1",
        project="noor", capabilities=["code"],
    ))
    await registry.upsert_agent(AgentInfo(
        agent_id="cx-mailo", agent_name="codex", version="1",
        project="mailo", capabilities=["code"],
    ))
    agents = await registry.list_agents(project="noor")
    assert len(agents) == 1
    assert agents[0].agent_name == "claude-code"


@pytest.mark.asyncio
async def test_get_agent_not_found(registry):
    result = await registry.get_agent("nonexistent")
    assert result is None
