"""Tests for the benchmark harness metric-shaping and report rendering."""
from types import SimpleNamespace

from benchmarks.harness import shape_metrics
from benchmarks.report import generate_report


def test_shape_metrics_is_self_describing():
    stats = SimpleNamespace(nodes=536, edges=4050, communities=12)
    m = shape_metrics(
        system="loom-os",
        repo_sha="80fa21a",
        build_time_s=1.234,
        stats=stats,
        latencies_ms=[10.0, 20.0, 30.0],
    )
    assert m["system"] == "loom-os"
    assert m["repo_sha"] == "80fa21a"
    assert m["build_time_s"] == 1.23          # rounded to 2dp
    assert m["nodes"] == 536
    assert m["edges"] == 4050
    assert m["communities"] == 12
    assert m["avg_query_latency_ms"] == 20.0  # mean of 10/20/30
    assert m["queries_run"] == 3


def test_report_renders_only_measured_numbers(tmp_path):
    loom = {
        "system": "loom-os", "repo_sha": "80fa21a", "build_time_s": 1.2,
        "nodes": 536, "edges": 4050, "communities": 12,
        "avg_query_latency_ms": 18.4, "queries_run": 4,
    }
    cognee = {"system": "cognee", "not_measured": True}
    out = tmp_path / "BENCHMARKS.md"
    md = generate_report([loom, cognee], output_path=str(out))

    assert "loom-os" in md and "cognee" in md
    assert "18.4" in md                 # real measured latency present
    assert "not measured" in md         # competitor not fabricated
    assert "200-500ms" not in md        # old hardcoded estimate is gone
    assert out.read_text() == md        # written to disk
