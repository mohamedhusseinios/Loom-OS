"""Generate a markdown benchmark report from harness output.

Usage:
    python -m benchmarks.report benchmarks/results.json
"""
import json
from pathlib import Path


def generate_report(metrics: dict, output_path: str = "benchmarks/report.md") -> str:
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

- **Single-process daemon** (no Docker/Neo4j)
- **SQLite** for persistence
- **NumPy** for vector similarity
- **sentence-transformers** all-MiniLM-L6-v2 for embeddings
- **graph.json mtime cache** — zero repeated JSON parsing

## Why It's Fast

1. No network round-trips — everything is local
2. mtime-based graph cache avoids re-parsing graph.json
3. NumPy cosine similarity is O(n) with no index overhead for <10K docs
4. Single-process means no IPC, no serialization, no Docker layer

## Comparison

| Feature | Loom OS | Cognee | Graphiti |
|---------|---------|--------|----------|
| Infrastructure | `pip install` | Docker + Neo4j | Docker + Neo4j |
| Setup time | ~30s | ~10min | ~10min |
| Query latency | {metrics['avg_query_latency_ms']}ms | ~200-500ms* | ~200-500ms* |

*Competitor numbers are estimates; run equivalent tasks for precise comparison.
"""
    Path(output_path).write_text(md)
    return md


if __name__ == "__main__":
    import sys
    metrics = json.loads(Path(sys.argv[1]).read_text())
    report = generate_report(metrics)
    print(report)
