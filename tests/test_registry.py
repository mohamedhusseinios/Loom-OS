"""Tests for the Agent Registry."""
import pytest
from daemon.registry import AgentRegistry, ProjectExistsError
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

@pytest.mark.asyncio
async def test_create_and_delete_project(registry):
    project = await registry.create_project("test-proj", "Test Project", "/tmp/test")
    assert project is not None
    assert project.project_id == "test-proj"
    assert project.project_name == "Test Project"
    assert project.project_path == "/tmp/test"

    deleted = await registry.delete_project("test-proj")
    assert deleted is True

    gone = await registry.get_project("test-proj")
    assert gone is None

@pytest.mark.asyncio
async def test_delete_nonexistent_project(registry):
    deleted = await registry.delete_project("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_create_duplicate_project_raises(registry):
    """Re-creating the same project id surfaces a typed error (→ 409 in API)."""
    await registry.create_project("dup", "Dup", "/tmp/dup")
    with pytest.raises(ProjectExistsError):
        await registry.create_project("dup", "Dup", "/tmp/dup")


@pytest.mark.asyncio
async def test_create_task_is_idempotent(registry):
    """Replaying the same task_id (watcher reprocessing) must not error.

    Regression: the API writes a task row, then the inbox watcher reprocesses
    the dropped file and calls create_task again. Before INSERT OR IGNORE this
    raised IntegrityError on the PRIMARY KEY.
    """
    created_first = await registry.create_task("t1", "noor", "claude-code", "do thing", "high")
    created_second = await registry.create_task("t1", "noor", "claude-code", "do thing", "high")

    assert created_first is True, "first insert should report creation"
    assert created_second is False, "duplicate task_id must be a no-op, not an error"

    tasks = await registry.list_tasks("noor")
    assert len(tasks) == 1, "idempotent insert must not duplicate the row"


@pytest.mark.asyncio
async def test_append_and_list_progress(tmp_path):
    from daemon.registry import AgentRegistry
    reg = AgentRegistry(str(tmp_path / "t.db"))
    await reg.initialize()
    s1 = await reg.append_progress("t1", "milestone", "worktree created")
    s2 = await reg.append_progress("t1", "tool", "tool: Edit")
    assert (s1, s2) == (1, 2)
    items = await reg.list_progress("t1")
    assert [i.seq for i in items] == [1, 2]
    assert items[0].kind == "milestone"
    assert items[1].message == "tool: Edit"
    # isolation between tasks
    assert await reg.list_progress("other") == []
    await reg.close()


@pytest.mark.asyncio
async def test_create_agent_task_explicit_id_is_idempotent(tmp_path):
    from daemon.registry import AgentRegistry
    from daemon.models import AgentTaskCreatePayload, AgentTaskStatus
    reg = AgentRegistry(str(tmp_path / "t.db"))
    await reg.initialize()
    payload = AgentTaskCreatePayload(
        project="noor", title="T", instruction="do", assignee="claude-code-noor")
    id1 = await reg.create_agent_task(payload, task_id="fixed-1", status=AgentTaskStatus.READY)
    id2 = await reg.create_agent_task(payload, task_id="fixed-1", status=AgentTaskStatus.READY)
    assert id1 == id2 == "fixed-1"
    rec = await reg.get_agent_task("fixed-1")
    assert rec.status == AgentTaskStatus.READY
    assert rec.assignee == "claude-code-noor"
    tasks = await reg.list_agent_tasks("noor")
    assert sum(1 for t in tasks if t.id == "fixed-1") == 1  # only one row
    await reg.close()
