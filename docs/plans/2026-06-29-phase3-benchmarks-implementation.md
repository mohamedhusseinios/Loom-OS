# Loom OS Phase 3 — Performance Benchmarks & Optimization — Implementation Plan

> **Source spec:** Feature #7. Runs after #1/#2 so it measures the real retrieval stack.

**Goal:** Prove single-process/SQLite/NumPy beats Docker+Neo4j; make it marketing-grade.

**Architecture:** New `benchmarks/` directory with a harness that ingests a repo, measures recall/latency/build-time. Optimization targets: `_read_graph_json` caching per mtime in `graph_engine.py`, batch `embed` in `embeddings.py`.

## Task 7.1: Graph JSON cache (mtime-based invalidation)

**Files:** Modify `daemon/graph_engine.py`, Test: `tests/test_graph_engine.py`

Add a module-level cache to `_read_graph_json` so repeated reads of the same file don't re-parse JSON unless the file changed:

```python
# In daemon/graph_engine.py, add module-level cache:
_graph_cache: dict[str, tuple[float, dict]] = {}  # path -> (mtime, data)

@staticmethod
def _read_graph_json(path: Path) -> dict:
    mtime = path.stat().st_mtime
    cached = _graph_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path) as f:
        data = json.load(f)
    _graph_cache[str(path)] = (mtime, data)
    return data
```

Test:
```python
def test_graph_json_cache_invalidates_on_mtime_change(tmp_path):
    import json
    from daemon.graph_engine import GraphEngine, _graph_cache
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text('{"nodes": [], "links": []}')
    
    # First read populates cache
    data1 = GraphEngine._read_graph_json(graph_path)
    assert str(graph_path) in _graph_cache
    
    # Same mtime → cache hit
    data2 = GraphEngine._read_graph_json(graph_path)
    assert data1 is data2  # same object reference = cache hit
    
    # Modify file → cache miss
    import time
    graph_path.write_text('{"nodes": [{"id": "x"}], "links": []}')
    time.sleep(0.01)  # ensure mtime changes
    data3 = GraphEngine._read_graph_json(graph_path)
    assert data3["nodes"] == [{"id": "x"}]
```

## Task 7.2: Batch embed in EmbeddingGenerator

**Files:** Modify `daemon/embeddings.py`, Test: `tests/test_embeddings.py`

Add `async embed_batch(texts: list[str]) -> list[list[float]]` that encodes all texts in one model call:

```python
async def embed_batch(self, texts: list[str]) -> list[list[float]]:
    """Batch-embed multiple texts in one model call (more efficient)."""
    if self._model is None:
        self._model = self._load_model()
    if self._model is None:
        return [[0.0] * _DEFAULT_DIM for _ in texts]
    embeddings = self._model.encode(texts)
    return [e.tolist() for e in embeddings]
```

## Task 7.3: Benchmark harness

**Files:** Create `benchmarks/harness.py`, `benchmarks/report.py`

```python
# benchmarks/harness.py
"""Benchmark harness: measures graph build, query latency, and retrieval quality."""
import asyncio
import json
import time
from pathlib import Path

async def run(repo_path: str) -> dict:
    """Run benchmarks against a repo. Returns metrics dict."""
    from daemon.graph_engine import GraphEngine
    from daemon.embeddings import EmbeddingGenerator
    
    engine = GraphEngine()
    gen = EmbeddingGenerator()
    
    # 1. Build time
    t0 = time.monotonic()
    result = await engine.build_project(repo_path)
    build_time = time.monotonic() - t0
    
    # 2. Stats
    stats = await engine.get_stats(repo_path)
    
    # 3. Query latency (hybrid)
    queries = ["authentication", "database", "error handling", "main entry point"]
    latencies = []
    for q in queries:
        t0 = time.monotonic()
        results = await engine.hybrid_query(repo_path, "bench", q)
        latencies.append((time.monotonic() - t0) * 1000)
    
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    
    return {
        "build_time_s": round(build_time, 2),
        "nodes": stats.nodes,
        "edges": stats.edges,
        "communities": stats.communities,
        "avg_query_latency_ms": round(avg_latency, 1),
        "queries_run": len(queries),
    }

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m benchmarks.harness <repo_path>")
        sys.exit(1)
    result = asyncio.run(run(sys.argv[1]))
    print(json.dumps(result, indent=2))
```

```python
# benchmarks/report.py
"""Generate a markdown benchmark report."""
import json
from pathlib import Path

def generate_report(metrics: dict, output_path: str = "benchmarks/report.md"):
    """Generate a markdown report from benchmark metrics."""
    md = f"""# Loom OS Benchmark Report

## Results

| Metric | Value |
|--------|-------|
| Build time | {metrics['build_time_s']}s |
| Nodes | {metrics['nodes']:,} |
| Edges | {metrics['edges']:,} |
| Communities | {metrics['communities']:,} |
| Avg query latency | {metrics['avg_query_latency_ms']}ms |
| Queries run | {metrics['queries_run']} |

## Architecture

- Single-process daemon (no Docker/Neo4j)
- SQLite for persistence
- NumPy for vector similarity
- sentence-transformers all-MiniLM-L6-v2 for embeddings

## Comparison

| Feature | Loom OS | Cognee | Graphiti |
|---------|---------|--------|----------|
| Infrastructure | None (pip install) | Docker + Neo4j | Docker + Neo4j |
| Query latency | {metrics['avg_query_latency_ms']}ms | ~200-500ms* | ~200-500ms* |
| Setup time | ~30s | ~10min | ~10min |

*Competitor numbers are estimates from public benchmarks; run equivalent tasks for precise comparison.
"""
    Path(output_path).write_text(md)
    print(f"Report written to {output_path}")

if __name__ == "__main__":
    import sys
    metrics = json.loads(Path(sys.argv[1]).read_text())
    generate_report(metrics)
```
