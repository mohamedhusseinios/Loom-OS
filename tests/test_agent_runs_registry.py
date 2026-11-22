"""Registry persistence for phase-1 agent_runs rows."""

import sqlite3

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


@pytest.mark.asyncio
async def test_create_agent_run_persists_selection_columns(registry):
    run = await registry.create_agent_run(
        task_id="task-selection",
        project="noor",
        run_dir="/tmp/runs/selection",
        status="pending_selection",
        schema_version=2,
        pattern_versions_json='{"react":"1.2.0"}',
        recommended_json='{"family_id":"react"}',
        chosen_source="auto",
        user_override=True,
        stage1_profile_json='{"kind":"frontend"}',
        fit_levels_json='{"react":"high"}',
        selection_scores_json='{"react":0.95}',
        selection_filter_provider="deepseek",
        selection_judgment_provider="anthropic",
        selection_filter_skipped=False,
        selection_judgment_skipped=True,
        selection_skip_reason="single candidate",
    )

    loaded = await registry.get_agent_run(run.id)
    assert loaded is not None
    assert loaded.status == "pending_selection"
    assert loaded.schema_version == 2
    assert loaded.pattern_versions_json == '{"react":"1.2.0"}'
    assert loaded.recommended_json == '{"family_id":"react"}'
    assert loaded.chosen_source == "auto"
    assert loaded.user_override is True
    assert loaded.stage1_profile_json == '{"kind":"frontend"}'
    assert loaded.fit_levels_json == '{"react":"high"}'
    assert loaded.selection_scores_json == '{"react":0.95}'
    assert loaded.selection_filter_provider == "deepseek"
    assert loaded.selection_judgment_provider == "anthropic"
    assert loaded.selection_filter_skipped is False
    assert loaded.selection_judgment_skipped is True
    assert loaded.selection_skip_reason == "single candidate"


@pytest.mark.asyncio
async def test_update_agent_run_patches_selection_columns(registry):
    run = await registry.create_agent_run(
        task_id="task-update",
        project="noor",
        run_dir="/tmp/runs/update",
        chosen_source="auto",
    )

    updated = await registry.update_agent_run(
        run.id,
        chosen_source="user",
        user_override=True,
        recommended_json='{"family_id":"python"}',
    )

    assert updated is not None
    assert updated.chosen_source == "user"
    assert updated.user_override is True
    assert updated.recommended_json == '{"family_id":"python"}'


@pytest.mark.asyncio
async def test_initialize_adds_selection_columns_to_legacy_agent_runs(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as db:
        db.execute("""
            CREATE TABLE agent_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                project TEXT NOT NULL,
                family_id TEXT NOT NULL DEFAULT 'react',
                modifier_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                worktree_path TEXT,
                run_dir TEXT,
                step_limit INTEGER NOT NULL DEFAULT 40,
                token_limit INTEGER NOT NULL DEFAULT 100000,
                cost_limit REAL NOT NULL DEFAULT 1.0,
                steps_used INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                cost_used REAL NOT NULL DEFAULT 0,
                stop_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO agent_runs"
            " (id, task_id, project, status, run_dir, created_at, updated_at)"
            " VALUES ('legacy-run', 'task-legacy', 'noor', 'running', '/tmp/legacy', 'now', 'now')"
        )

    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    try:
        cursor = await reg.db.execute("PRAGMA table_info(agent_runs)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert {
            "schema_version", "pattern_versions_json", "recommended_json", "chosen_source",
            "user_override", "stage1_profile_json", "fit_levels_json", "selection_scores_json",
            "selection_filter_provider", "selection_judgment_provider",
            "selection_filter_skipped", "selection_judgment_skipped", "selection_skip_reason",
        } <= columns
        loaded = await reg.get_agent_run("legacy-run")
        assert loaded is not None
        assert loaded.schema_version == 1
        assert loaded.pattern_versions_json == "{}"
        assert loaded.user_override is False
        assert loaded.chosen_source is None
    finally:
        await reg.close()


def test_loom_run_dir_uses_home_loom_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_runtime_module.Path, "home", staticmethod(lambda: tmp_path))
    assert loom_run_dir("abc") == tmp_path / ".loom" / "runs" / "abc"
