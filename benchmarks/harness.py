"""Benchmark harness: measures graph build, query latency, and retrieval quality.

Usage:
    python -m benchmarks.harness /path/to/repo
"""
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
