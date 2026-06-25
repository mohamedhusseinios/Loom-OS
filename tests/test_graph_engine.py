"""Tests for the Graph Engine."""
import pytest
from daemon.graph_engine import GraphEngine


@pytest.mark.asyncio
async def test_get_stats_no_graph(tmp_path):
    """Stats should return zeros when no graph exists."""
    engine = GraphEngine()
    project_path = str(tmp_path)
    stats = await engine.get_stats(project_path)
    assert stats.nodes == 0
    assert stats.edges == 0
    assert stats.communities == 0


@pytest.mark.asyncio
async def test_available_when_graphify_installed():
    engine = GraphEngine()
    # graphifyy is installed in the dev venv, so this should be True
    assert engine.available is True


@pytest.mark.asyncio
async def test_build_without_graphify_returns_failed():
    """If graphify not importable, build should return failed gracefully."""
    # We can test the error path by checking the subprocess case
    # The engine currently shells out to `graphify` CLI; if CLI not on PATH it fails
    engine = GraphEngine()
    if engine.available:
        result = await engine.build_project("/tmp/nonexistent-project-12345")
        assert result.status == "failed"
    else:
        result = await engine.build_project("/tmp/test")
        assert result.status == "failed"
        assert "not installed" in (result.error or "")
