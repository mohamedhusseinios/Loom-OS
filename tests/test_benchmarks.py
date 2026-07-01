"""Tests for the benchmark harness metric-shaping and report rendering."""
from types import SimpleNamespace

from benchmarks.harness import shape_metrics


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
