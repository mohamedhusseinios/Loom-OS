"""Tests for the RecallEngine."""
import json
import pytest
from daemon.recall import RecallEngine


@pytest.fixture
def engine(tmp_path):
    """Return a RecallEngine scoped to a temp directory."""
    return RecallEngine(loom_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_recall_context_for_known_entities(engine, tmp_path):
    """Recall returns context when a project graph has matching entities."""
    # Simulate a project graph
    project_dir = tmp_path / "test-proj"
    graph_out = project_dir / "graphify-out"
    graph_out.mkdir(parents=True)
    graph_json = graph_out / "graph.json"
    graph_json.write_text(json.dumps({
        "nodes": [
            {"name": "auth.py", "kind": "Module"},
            {"name": "authenticate_user", "kind": "Function"},
            {"name": "middleware.py", "kind": "Module"},
        ]
    }))

    context = await engine.recall(
        agent_id="agent-1",
        project="test-proj",
        project_path=str(project_dir),
        task_hint="auth refactor",
    )
    assert context is not None
    assert isinstance(context, str)
    assert len(context) > 0
    assert "auth.py" in context
    assert "authenticate_user" in context


@pytest.mark.asyncio
async def test_recall_no_graph_returns_empty(engine):
    """Recall returns empty string when no graph exists."""
    context = await engine.recall(
        agent_id="agent-1",
        project="nonexistent",
        project_path="/nonexistent/path",
    )
    assert context == ""


@pytest.mark.asyncio
async def test_recall_no_matching_entities_returns_empty(engine, tmp_path):
    """Recall returns empty string when graph has no matching entities."""
    project_dir = tmp_path / "no-match"
    graph_out = project_dir / "graphify-out"
    graph_out.mkdir(parents=True)
    graph_json = graph_out / "graph.json"
    graph_json.write_text(json.dumps({
        "nodes": [
            {"name": "utils.py", "kind": "Module"},
            {"name": "helper_func", "kind": "Function"},
        ]
    }))

    context = await engine.recall(
        agent_id="agent-1",
        project="no-match",
        project_path=str(project_dir),
        task_hint="database migration",
    )
    assert context == ""
