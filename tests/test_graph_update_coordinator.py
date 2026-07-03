"""Tests for GraphUpdateCoordinator — gate / coalesce / throttle / debounce / error."""
import asyncio
import pytest

from daemon.graph_update_coordinator import GraphUpdateCoordinator
from daemon.models import BuildResult


class FakeEngine:
    """Records graphify calls; optionally blocks builds on an Event."""

    def __init__(self):
        self.calls = []            # ordered list of "build" | "extract" | "cluster"
        self.build_duration = 0.0
        self.extract_duration = 0.0
        self.cluster_duration = 0.0
        self.status = "completed"
        self.gate = None           # optional asyncio.Event to hold a call open

    async def _maybe_block(self):
        if self.gate is not None:
            await self.gate.wait()

    async def build_project(self, path):
        self.calls.append("build")
        await self._maybe_block()
        return BuildResult(project="p", status=self.status, nodes=1, edges=1,
                           duration_s=self.build_duration)

    async def extract_only(self, path):
        self.calls.append("extract")
        await self._maybe_block()
        return BuildResult(project="p", status=self.status, nodes=1, edges=1,
                           duration_s=self.extract_duration)

    async def cluster_only(self, path):
        self.calls.append("cluster")
        await self._maybe_block()
        return BuildResult(project="p", status=self.status, nodes=1, edges=1,
                           duration_s=self.cluster_duration)


def make_coordinator(engine, **kw):
    updates = []

    async def on_updated(project, path, result):
        updates.append((project, result.status))

    defaults = dict(defer_threshold_s=5.0, min_interval_s=0.01,
                    max_interval_s=0.05, cluster_debounce_s=0.02)
    defaults.update(kw)
    coord = GraphUpdateCoordinator(engine, on_updated, **defaults)
    return coord, updates


@pytest.mark.asyncio
async def test_fast_project_uses_inline_full_build():
    engine = FakeEngine()
    engine.build_duration = 1.0
    coord, updates = make_coordinator(engine)
    coord.record_full_build("p", 1.0)          # fast (< 5s gate) → inline full build
    await coord.request_update("p", "/repo")
    await asyncio.sleep(0.05)
    assert engine.calls == ["build"]
    assert updates == [("p", "completed")]


@pytest.mark.asyncio
async def test_slow_project_defers_clustering():
    engine = FakeEngine()
    engine.extract_duration = 2.0
    engine.cluster_duration = 3.0
    coord, updates = make_coordinator(engine)
    coord.record_full_build("p", 10.0)         # slow (> 5s gate) → deferred mode
    await coord.request_update("p", "/repo")
    await asyncio.sleep(0.01)
    assert engine.calls == ["extract"]         # fast path first, no clustering yet
    await asyncio.sleep(0.05)                  # let the debounce (0.02) fire
    assert engine.calls == ["extract", "cluster"]
    assert updates == [("p", "completed"), ("p", "completed")]  # two emits per burst


@pytest.mark.asyncio
async def test_overlapping_updates_coalesce_into_one_followup():
    engine = FakeEngine()
    engine.gate = asyncio.Event()              # hold the first build open
    coord, updates = make_coordinator(engine)
    coord.record_full_build("p", 1.0)          # fast → full builds
    await coord.request_update("p", "/repo")   # starts build #1 (blocks on gate)
    await asyncio.sleep(0.01)
    await coord.request_update("p", "/repo")   # in-progress → marks dirty, no 2nd start
    await coord.request_update("p", "/repo")   # still in-progress → still just dirty
    assert engine.calls == ["build"]           # exactly one build running
    engine.gate.set()                          # release build #1
    await asyncio.sleep(0.1)                    # followup fires → build #2 (coalesced)
    assert engine.calls == ["build", "build"]  # two total, never concurrent


@pytest.mark.asyncio
async def test_throttled_update_still_builds_on_trailing_edge():
    engine = FakeEngine()
    coord, updates = make_coordinator(engine, min_interval_s=0.05, max_interval_s=0.05)
    coord.record_full_build("p", 1.0)
    await coord.request_update("p", "/repo")   # build #1 runs immediately
    await asyncio.sleep(0.01)
    await coord.request_update("p", "/repo")   # within 0.05s interval → throttled + trailing
    assert engine.calls == ["build"]
    await asyncio.sleep(0.1)                    # trailing edge → build #2
    assert engine.calls == ["build", "build"]


@pytest.mark.asyncio
async def test_failed_build_does_not_wedge_project():
    engine = FakeEngine()
    engine.status = "failed"                   # build fails
    coord, updates = make_coordinator(engine)
    coord.record_full_build("p", 1.0)
    await coord.request_update("p", "/repo")
    await asyncio.sleep(0.05)
    assert engine.calls == ["build"]
    assert coord._state["p"].in_progress is False   # cleared despite failure
    # a later update can still run
    await asyncio.sleep(0.1)
    await coord.request_update("p", "/repo")
    await asyncio.sleep(0.05)
    assert engine.calls == ["build", "build"]
