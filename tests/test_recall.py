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


@pytest.mark.asyncio
async def test_retain_extracts_learnings_to_inbox(engine, tmp_path):
    """retain() writes FOUND/PATTERN/DECISION lines as finding-*.md in the inbox."""
    project_inbox = tmp_path / "inbox" / "test-proj"

    agent_output = """
    FOUND: auth.py has a hardcoded secret on line 42
    PATTERN: Circular dependency between auth.py and middleware.py
    DECISION: Extract auth config to env vars, split middleware into auth_middleware.py
    """
    await engine.retain(
        agent_id="agent-1",
        project="test-proj",
        agent_output=agent_output,
        inbox_dir=project_inbox,
    )

    findings_files = sorted(project_inbox.glob("finding-*.md"))
    assert len(findings_files) == 3

    # Each file should contain one of the extracted lines
    all_content = "".join(f.read_text() for f in findings_files)
    assert "hardcoded secret" in all_content
    assert "Circular dependency" in all_content
    assert "Extract auth config" in all_content


@pytest.mark.asyncio
async def test_retain_no_structured_output_writes_nothing(engine, tmp_path):
    """retain() is a no-op when agent output has no structured findings."""
    project_inbox = tmp_path / "inbox" / "test-proj"

    await engine.retain(
        agent_id="agent-2",
        project="test-proj",
        agent_output="Just some random text without any markers.",
        inbox_dir=project_inbox,
    )
    assert not list(project_inbox.glob("finding-*.md"))


@pytest.mark.asyncio
async def test_cross_agent_synthesis_inherits_patterns(engine, tmp_path):
    """Agent B's recall() discovers findings that Agent A retained."""
    project_dir = tmp_path / "test-proj"
    inbox = tmp_path / "inbox" / "test-proj"

    # Agent A discovers a pattern and retains it
    await engine.retain(
        agent_id="agent-a",
        project="test-proj",
        agent_output="PATTERN: auth.py always uses bcrypt for password hashing",
        inbox_dir=inbox,
    )

    # Agent B works on auth — should get Agent A's pattern via recall
    context = await engine.recall(
        agent_id="agent-b",
        project="test-proj",
        project_path=str(project_dir),
        task_hint="auth password hashing",
    )
    assert "bcrypt" in context
    assert "PATTERN" in context


@pytest.mark.asyncio
async def test_cross_agent_synthesis_no_match_if_irrelevant(engine, tmp_path):
    """Recall only returns findings whose content matches the task hint."""
    inbox = tmp_path / "inbox" / "test-proj"

    await engine.retain(
        agent_id="agent-a",
        project="test-proj",
        agent_output="PATTERN: auth.py always uses bcrypt for password hashing",
        inbox_dir=inbox,
    )

    # Agent B works on unrelated task — should NOT get auth findings
    context = await engine.recall(
        agent_id="agent-b",
        project="test-proj",
        project_path=str(tmp_path / "test-proj"),
        task_hint="database migration",
    )
    assert "bcrypt" not in context
