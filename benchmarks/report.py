"""Generate a markdown benchmark report from harness output.

Usage:
    python -m benchmarks.report benchmarks/results.json
"""
import json
from pathlib import Path

_HEADER = """# Loom OS Benchmarks

> Reproducible head-to-head measurements. Every number below was measured on the
> same task and repo commit. Cells marked **not measured** were not run — Loom does
> not publish estimated competitor numbers. See `benchmarks/README.md` to reproduce.

## Why Loom is structurally fast

- Single-process daemon — no Docker, no Neo4j, no network round-trips.
- `graph.json` mtime cache — zero repeated JSON parsing.
- NumPy cosine similarity — O(n), no index overhead below ~10K docs.

## Results
"""


def _cell(sys_metrics, key, suffix=""):
    if sys_metrics.get("not_measured"):
        return "not measured"
    val = sys_metrics.get(key)
    return f"{val:,}{suffix}" if isinstance(val, int) else f"{val}{suffix}"


def generate_report(systems: list[dict], output_path: str = "BENCHMARKS.md") -> str:
    """Render an honest comparison table from measured metrics only."""
    rows = ["| System | Repo @ | Build time | Nodes | Edges | Avg query latency |",
            "|--------|--------|-----------|-------|-------|-------------------|"]
    for s in systems:
        sha = s.get("repo_sha", "—") if not s.get("not_measured") else "—"
        rows.append(
            f"| {s['system']} | {sha} | {_cell(s, 'build_time_s', 's')} | "
            f"{_cell(s, 'nodes')} | {_cell(s, 'edges')} | "
            f"{_cell(s, 'avg_query_latency_ms', 'ms')} |"
        )
    md = _HEADER + "\n" + "\n".join(rows) + "\n"
    Path(output_path).write_text(md)
    return md


if __name__ == "__main__":
    import sys
    data = json.loads(Path(sys.argv[1]).read_text())
    # Handle both single dict (legacy) and list of dicts (new)
    systems = data if isinstance(data, list) else [data]
    report = generate_report(systems)
    print(report)
