"""Registry persistence for phase-1 agent_runs rows."""

import pytest

import daemon.agent_runtime as agent_runtime_module
from daemon.agent_runtime import loom_run_dir
from daemon.models import AgentRunRecord
from daemon.registry import AgentRegistry


@pytest.fixture
async def registry(tmp_path):
    reg = AgentRegistry(str(tmp_path / "test.db"))
    await reg.initialize()
    yield reg
    await reg.close()


@pytest.mark.asyncio
async def test_create_agent_run_persists_phase1_columns(registry):
    run = await registry.create_agent_run(
        task_id="task-1",
        project="noor",
        run_dir="/tmp/runs/abc",
        worktree_path="/tmp/wt",
    )
    assert isinstance(run, AgentRunRecord)
    assert run.task_id == "task-1"
    assert run.project == "noor"
    assert run.family_id == "react"
    assert run.modifier_ids_json == "[]"
    assert run.status == "running"
    assert run.worktree_path == "/tmp/wt"
    assert run.run_dir == "/tmp/runs/abc"
    assert run.step_limit == 40
    assert run.token_limit == 100000
    assert run.cost_limit == 1.0
    assert run.steps_used == 0
    assert run.tokens_used == 0
    assert run.cost_used == 0.0
    assert run.stop_reason is None
    assert run.created_at
    assert run.updated_at

    loaded = await registry.get_agent_run(run.id)
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.family_id == "react"
    assert loaded.modifier_ids_json == "[]"
    assert loaded.step_limit == 40
    assert loaded.token_limit == 100000
    assert loaded.cost_limit == 1.0

    missing = await registry.get_agent_run("does-not-exist")
    assert missing is None

    listed = await registry.list_agent_runs(task_id="task-1")
    assert [row.id for row in listed] == [run.id]


def test_loom_run_dir_uses_home_loom_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_runtime_module.Path, "home", staticmethod(lambda: tmp_path))
    assert loom_run_dir("abc") == tmp_path / ".loom" / "runs" / "abc"
