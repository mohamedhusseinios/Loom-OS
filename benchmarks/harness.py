"""Benchmark harness: measures graph build, query latency, and retrieval quality.

Usage:
    python -m benchmarks.harness /path/to/repo
"""
import asyncio
import json
import subprocess
import time
from pathlib import Path


def shape_metrics(system, repo_sha, build_time_s, stats, latencies_ms):
    """Shape raw benchmark measurements into a self-describing metrics dict."""
    avg = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0
    return {
        "system": system,
        "repo_sha": repo_sha,
        "build_time_s": round(build_time_s, 2),
        "nodes": stats.nodes,
        "edges": stats.edges,
        "communities": stats.communities,
        "avg_query_latency_ms": round(avg, 1),
        "queries_run": len(latencies_ms),
    }


async def run(repo_path: str, system: str = "loom-os") -> dict:
    """Run benchmarks against a repo. Returns a self-describing metrics dict."""
    from daemon.graph_engine import GraphEngine

    engine = GraphEngine()

    t0 = time.monotonic()
    await engine.build_project(repo_path)
    build_time = time.monotonic() - t0

    stats = await engine.get_stats(repo_path)

    queries = ["authentication", "database", "error handling", "main entry point"]
    latencies = []
    for q in queries:
        t0 = time.monotonic()
        await engine.hybrid_query(repo_path, "bench", q)
        latencies.append((time.monotonic() - t0) * 1000)

    try:
        repo_sha = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:
        repo_sha = "unknown"

    return shape_metrics(system, repo_sha, build_time, stats, latencies)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m benchmarks.harness <repo_path>")
        sys.exit(1)
    result = asyncio.run(run(sys.argv[1]))
    print(json.dumps(result, indent=2))
