"""Tests for the Kanban task board (agent_tasks)."""
import pytest
from daemon.registry import AgentRegistry
from daemon.models import AgentTaskCreatePayload, AgentTaskStatus


@pytest.fixture
async def registry(tmp_path):
    db_path = tmp_path / "test.db"
    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    yield reg
    await reg.close()


@pytest.mark.asyncio
async def test_create_and_get_agent_task(registry):
    """Creating and retrieving an agent task works."""
    task_id = await registry.create_agent_task(
        AgentTaskCreatePayload(
            project="test-proj",
            title="Fix auth bug",
            instruction="Fix the hardcoded secret in auth.py",
            priority=1,
        )
    )
    assert task_id is not None

    record = await registry.get_agent_task(task_id)
    assert record is not None
    assert record.title == "Fix auth bug"
    assert record.status == AgentTaskStatus.TODO


@pytest.mark.asyncio
async def test_agent_task_state_transition(registry):
    """Agent tasks can transition between states."""
    task_id = await registry.create_agent_task(
        AgentTaskCreatePayload(project="test-proj", title="T1", instruction="Do X")
    )
    await registry.update_agent_task(task_id, status=AgentTaskStatus.RUNNING)

    record = await registry.get_agent_task(task_id)
    assert record.status == AgentTaskStatus.RUNNING

    await registry.update_agent_task(task_id, status=AgentTaskStatus.DONE)
    record = await registry.get_agent_task(task_id)
    assert record.status == AgentTaskStatus.DONE


@pytest.mark.asyncio
async def test_agent_task_dependency_auto_promotion(registry):
    """Child task auto-promotes to READY when all parent deps are DONE."""
    parent_id = await registry.create_agent_task(
        AgentTaskCreatePayload(project="test-proj", title="Parent", instruction="X")
    )
    await registry.update_agent_task(parent_id, status=AgentTaskStatus.DONE)

    child_id = await registry.create_agent_task(
        AgentTaskCreatePayload(
            project="test-proj",
            title="Child",
            instruction="Y",
            dependencies=[parent_id],
        )
    )
    child = await registry.get_agent_task(child_id)
    assert child.status == AgentTaskStatus.READY


@pytest.mark.asyncio
async def test_agent_task_dependency_stays_todo_if_parent_not_done(registry):
    """Child stays TODO if parent dependency is not DONE yet."""
    parent_id = await registry.create_agent_task(
        AgentTaskCreatePayload(project="test-proj", title="Parent", instruction="X")
    )

    child_id = await registry.create_agent_task(
        AgentTaskCreatePayload(
            project="test-proj",
            title="Child",
            instruction="Y",
            dependencies=[parent_id],
        )
    )
    child = await registry.get_agent_task(child_id)
    assert child.status == AgentTaskStatus.TODO


@pytest.mark.asyncio
async def test_list_agent_tasks_by_project(registry):
    """Listing tasks is filtered by project and excludes archived."""
    await registry.create_agent_task(
        AgentTaskCreatePayload(project="proj-a", title="A1", instruction="x")
    )
    await registry.create_agent_task(
        AgentTaskCreatePayload(project="proj-a", title="A2", instruction="x")
    )
    await registry.create_agent_task(
        AgentTaskCreatePayload(project="proj-b", title="B1", instruction="x")
    )

    tasks_a = await registry.list_agent_tasks("proj-a")
    assert len(tasks_a) == 2

    tasks_b = await registry.list_agent_tasks("proj-b")
    assert len(tasks_b) == 1


@pytest.mark.asyncio
async def test_list_agent_tasks_filters_archived(registry):
    """Archived tasks are excluded from list by default."""
    task_id = await registry.create_agent_task(
        AgentTaskCreatePayload(project="test-proj", title="Old", instruction="x")
    )
    await registry.update_agent_task(task_id, status=AgentTaskStatus.ARCHIVED)

    tasks = await registry.list_agent_tasks("test-proj")
    assert len(tasks) == 0
