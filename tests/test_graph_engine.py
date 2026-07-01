"""Tests for the Graph Engine."""
import json
import time
import pytest
from daemon.graph_engine import GraphEngine, _graph_cache, clear_graph_cache


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

    async def fake_embed_batch(self, texts):
        return [[float(len(t)), 1.0] for t in texts]
    monkeypatch.setattr("daemon.embeddings.EmbeddingGenerator.embed", fake_embed, raising=False)
    monkeypatch.setattr(
        "daemon.embeddings.EmbeddingGenerator.embed_batch", fake_embed_batch, raising=False
    )

    engine = GraphEngine()
    rows = await engine.hybrid_query(str(tmp_path), "proj-1", "AuthService", depth=1)

    ids = [r["id"] for r in rows]
    assert "AuthService" in ids                       # vector seed
    assert "BcryptHasher" in ids                      # reached via BFS
    bcrypt = next(r for r in rows if r["id"] == "BcryptHasher")
    assert bcrypt["structural_distance"] == 1
    assert "semantic_score" in bcrypt


def test_hybrid_query_batches_node_embeddings(monkeypatch, tmp_path):
    """hybrid_query must embed all node ids in ONE batch call, not per-node.

    Regression test for the O(nodes x queries) perf bug: the old code called
    ``await gen.embed(str(nid))`` for every node on every query (seed loop and
    again during BFS scoring), with no cache. ``embed_batch`` already exists
    and does one forward pass — this asserts it's actually used.
    """
    import json, asyncio
    from daemon.graph_engine import GraphEngine
    gdir = tmp_path / "graphify-out"; gdir.mkdir(parents=True)
    (gdir / "graph.json").write_text(json.dumps({
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "links": [{"source": "a", "target": "b"}],
    }))
    calls = {"embed": 0, "embed_batch": 0, "batch_sizes": []}
    class FakeGen:
        def __init__(self, *a, **k): pass
        async def embed(self, text):
            calls["embed"] += 1
            return [float(len(str(text))), 1.0, 0.0]
        async def embed_batch(self, texts):
            calls["embed_batch"] += 1
            calls["batch_sizes"].append(len(texts))
            return [[float(len(str(t))), 1.0, 0.0] for t in texts]
    monkeypatch.setattr("daemon.graph_engine.EmbeddingGenerator", FakeGen)
    res = asyncio.run(GraphEngine().hybrid_query(str(tmp_path), "proj", "q"))
    assert calls["embed_batch"] == 1        # all node ids embedded in one batch
    assert calls["batch_sizes"] == [3]      # exactly the 3 nodes
    assert calls["embed"] <= 1              # question only; no per-node embed loop
    assert isinstance(res, list)


def test_graph_json_cache_invalidates_on_mtime_change(tmp_path):
    """Cache returns same object on repeated reads; invalidates on file change."""
    clear_graph_cache()
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text('{"nodes": [], "links": []}')

    # First read populates cache
    data1 = GraphEngine._read_graph_json(graph_path)
    assert str(graph_path) in _graph_cache

    # Same mtime → cache hit (same object)
    data2 = GraphEngine._read_graph_json(graph_path)
    assert data1 is data2

    # Modify file → cache miss
    graph_path.write_text('{"nodes": [{"id": "x"}], "links": []}')
    time.sleep(0.01)  # ensure mtime changes
    data3 = GraphEngine._read_graph_json(graph_path)
    assert data3["nodes"] == [{"id": "x"}]

    clear_graph_cache()


def test_graph_json_cache_handles_missing_file(tmp_path):
    """Reading a non-existent path raises (same as before caching)."""
    clear_graph_cache()
    with pytest.raises(FileNotFoundError):
        GraphEngine._read_graph_json(tmp_path / "nonexistent.json")
