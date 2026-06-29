"""Tests for the Graph Engine."""
import json
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
async def test_build_uses_graphify_update_subcommand(tmp_path, monkeypatch):
    """build_project must invoke ``graphify update <path>`` (subcommand first).

    The buggy form ``graphify <path> --update`` makes graphify run its default
    full-extraction command (docs/papers/images), which requires an LLM API key,
    exits non-zero, and leaves graph.json as the empty stub — so the dashboard
    shows "build complete" over an empty graph.
    """
    engine = GraphEngine()
    if not engine.available:
        pytest.skip("graphify not installed")

    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Result()

    monkeypatch.setattr("daemon.graph_engine.subprocess.run", fake_run)

    await engine.build_project(str(tmp_path))

    assert captured["cmd"][:2] == ["graphify", "update"], captured["cmd"]
    assert captured["cmd"][2] == str(tmp_path), captured["cmd"]


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


@pytest.mark.asyncio
async def test_hybrid_query_returns_dual_relevance(tmp_path, monkeypatch):
    """hybrid_query returns nodes with both semantic_score and structural_distance."""
    # Minimal graph.json with two connected nodes.
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps({
        "nodes": [{"id": "AuthService", "kind": "class"},
                  {"id": "BcryptHasher", "kind": "class"}],
        "edges": [{"source": "AuthService", "target": "BcryptHasher", "kind": "uses"}],
    }))

    # Deterministic embedding: vector = [len(text)] so 'AuthService' seeds first.
    async def fake_embed(self, text):
        return [float(len(text)), 1.0]
    monkeypatch.setattr("daemon.embeddings.EmbeddingGenerator.embed", fake_embed, raising=False)

    engine = GraphEngine()
    rows = await engine.hybrid_query(str(tmp_path), "proj-1", "AuthService", depth=1)

    ids = [r["id"] for r in rows]
    assert "AuthService" in ids                       # vector seed
    assert "BcryptHasher" in ids                      # reached via BFS
    bcrypt = next(r for r in rows if r["id"] == "BcryptHasher")
    assert bcrypt["structural_distance"] == 1
    assert "semantic_score" in bcrypt
