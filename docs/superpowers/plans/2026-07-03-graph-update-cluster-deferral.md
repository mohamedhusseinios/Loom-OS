# Cost-Gated Cluster-Deferral (Graph-Update Path) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Spec:** [docs/superpowers/specs/2026-07-03-graph-update-cluster-deferral-design.md](../specs/2026-07-03-graph-update-cluster-deferral-design.md)

**Goal:** Cut per-update cost on large repos by deferring graphify's expensive global clustering off the finding hot-path (fast `--no-cluster` extract + a debounced trailing `cluster-only`), gated so normal repos keep today's inline behavior; and eliminate overlapping rebuilds via an in-progress guard + adaptive throttle.

**Architecture:** Three parts. (1) `GraphEngine` gains `extract_only`/`cluster_only` primitives and reports build `duration_s`. (2) A new `GraphUpdateCoordinator` owns per-project policy (cost gate, overlap coalescing, adaptive throttle, trailing cluster debounce) and is unit-tested with a fake engine — no real graphify. (3) `Router` delegates finding-driven updates to the coordinator.

**Tech Stack:** Python 3.11+, asyncio, pytest (`asyncio_mode=auto`), Pydantic. graphify CLI (subprocess). Tests mock `daemon.graph_engine.subprocess.run` via `monkeypatch` (existing pattern in `tests/test_graph_engine.py`).

## Global Constraints

- **Run tests with** `.venv/bin/python -m pytest tests/ -q` (bare `pytest` can't collect `tests/test_benchmarks.py` — pre-existing packaging gap). Baseline stays green.
- **Updates must never block inbox processing.** `Router._handle_finding` must not `await` the actual graph build; `coordinator.request_update(...)` returns immediately and schedules background work (mirrors today's `asyncio.create_task` behavior).
- **Never two concurrent graphify subprocesses per project.** The in-progress guard is a hard invariant.
- **Config as module constants** (mirroring today's `MIN_UPDATE_INTERVAL`): `DEFER_THRESHOLD_S=5.0`, `MIN_UPDATE_INTERVAL=30.0`, `MAX_UPDATE_INTERVAL=300.0`, `CLUSTER_DEBOUNCE_S=60.0`. All injectable via constructor kwargs so tests can pass tiny values.
- **graphify argv is exact:** extract = `graphify update <path> --no-cluster`; cluster = `graphify cluster-only <path> --no-viz`; full = `graphify update <path>` (unchanged). Subcommand comes first.
- **Commits:** conventional; `git add <specific files>` only (never `-A`/`-am`); end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **No new runtime dependencies.**

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `daemon/models.py` | Pydantic schemas | add `duration_s` to `BuildResult` |
| `daemon/graph_engine.py` | graphify subprocess wrapper | `_run_graphify_build(path, cluster=)`, `_run_graphify_cluster`, `_run_and_measure`, `extract_only`, `cluster_only`; measure duration |
| `daemon/graph_update_coordinator.py` | per-project update policy (**new**) | `GraphUpdateCoordinator` |
| `daemon/router.py` | inbox event routing | delegate finding-updates to the coordinator; seed the gate on register |
| `tests/test_graph_engine.py` | engine unit tests | add primitive + duration tests |
| `tests/test_graph_update_coordinator.py` | coordinator unit tests (**new**) | gate / coalesce / throttle / debounce / error |
| `tests/test_router.py` | router unit tests | delegation + gate-seeding tests |

---

### Task 1: GraphEngine cluster-aware primitives + `BuildResult.duration_s`

**Files:**
- Modify: `daemon/models.py` (`BuildResult`, ~line 114)
- Modify: `daemon/graph_engine.py` (add `import time`; `_run_graphify_build`, new `_run_graphify_cluster`, new `_run_and_measure`, `build_project`, new `extract_only`, new `cluster_only`)
- Test: `tests/test_graph_engine.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `BuildResult.duration_s: float = 0.0`
  - `async GraphEngine.build_project(project_path: str) -> BuildResult` (full extract+cluster; now sets `duration_s`)
  - `async GraphEngine.extract_only(project_path: str) -> BuildResult` (`graphify update <path> --no-cluster`)
  - `async GraphEngine.cluster_only(project_path: str) -> BuildResult` (`graphify cluster-only <path> --no-viz`)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_graph_engine.py` (note: `import time` is already at the top of that file):

```python
@pytest.mark.asyncio
async def test_extract_only_passes_no_cluster(tmp_path, monkeypatch):
    """extract_only runs ``graphify update <path> --no-cluster`` (clustering skipped)."""
    engine = GraphEngine()
    if not engine.available:
        pytest.skip("graphify not installed")
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Result()

    monkeypatch.setattr("daemon.graph_engine.subprocess.run", fake_run)
    result = await engine.extract_only(str(tmp_path))

    assert captured["cmd"][:2] == ["graphify", "update"], captured["cmd"]
    assert captured["cmd"][2] == str(tmp_path)
    assert "--no-cluster" in captured["cmd"], captured["cmd"]
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_cluster_only_runs_cluster_subcommand(tmp_path, monkeypatch):
    """cluster_only runs ``graphify cluster-only <path> --no-viz``."""
    engine = GraphEngine()
    if not engine.available:
        pytest.skip("graphify not installed")
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Result()

    monkeypatch.setattr("daemon.graph_engine.subprocess.run", fake_run)
    result = await engine.cluster_only(str(tmp_path))

    assert captured["cmd"][:2] == ["graphify", "cluster-only"], captured["cmd"]
    assert captured["cmd"][2] == str(tmp_path)
    assert "--no-viz" in captured["cmd"], captured["cmd"]
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_build_reports_duration(tmp_path, monkeypatch):
    """build_project populates BuildResult.duration_s with measured wall-time."""
    engine = GraphEngine()
    if not engine.available:
        pytest.skip("graphify not installed")

    def fake_run(cmd, *args, **kwargs):
        time.sleep(0.02)

        class _Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Result()

    monkeypatch.setattr("daemon.graph_engine.subprocess.run", fake_run)
    result = await engine.build_project(str(tmp_path))

    assert isinstance(result.duration_s, float)
    assert result.duration_s >= 0.02
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_graph_engine.py -q -k "extract_only or cluster_only or reports_duration"`
Expected: FAIL — `AttributeError: 'GraphEngine' object has no attribute 'extract_only'`.

- [ ] **Step 3: Add `duration_s` to `BuildResult`** in `daemon/models.py`:

```python
class BuildResult(BaseModel):
    project: str
    status: str  # "started" | "completed" | "failed"
    nodes: int = 0
    edges: int = 0
    error: Optional[str] = None
    duration_s: float = 0.0
```

- [ ] **Step 4: Update `daemon/graph_engine.py`.** Add `import time` to the top imports. Replace `_run_graphify_build`, `build_project`, and `update_project` with the block below, and add the three new methods (place them together in the "Build / update" section):

```python
    def _run_graphify_build(self, project_path: str, cluster: bool = True):
        """Run ``graphify update`` (code-only, no LLM). ``cluster=False`` appends
        ``--no-cluster`` to skip the expensive global clustering pass.

        If no ``graph.json`` exists yet, create a minimal stub first —
        ``graphify update`` needs an existing graph to update.
        """
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            graph_path.write_text('{"nodes":[],"links":[]}')

        cmd = ["graphify", "update", project_path]
        if not cluster:
            cmd.append("--no-cluster")
        try:
            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(_decode_subprocess_error(e)) from e

    def _run_graphify_cluster(self, project_path: str):
        """Re-run global clustering on the existing graph.json (no re-extraction)."""
        try:
            subprocess.run(
                ["graphify", "cluster-only", project_path, "--no-viz"],
                capture_output=True,
                timeout=300,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(_decode_subprocess_error(e)) from e

    async def _run_and_measure(self, project_path: str, runner) -> BuildResult:
        """Run a graphify step in a thread, measure wall-time, shape a BuildResult."""
        project_name = Path(project_path).name
        if not self.available:
            return BuildResult(
                project=project_name, status="failed", error="Graphify not installed"
            )
        t0 = time.monotonic()
        try:
            await asyncio.to_thread(runner, project_path)
        except Exception as e:
            return BuildResult(
                project=project_name, status="failed", error=str(e),
                duration_s=time.monotonic() - t0,
            )
        duration = time.monotonic() - t0
        stats = await self.get_stats(project_path)
        return BuildResult(
            project=project_name, status="completed",
            nodes=stats.nodes, edges=stats.edges, duration_s=duration,
        )

    async def build_project(self, project_path: str) -> BuildResult:
        """Full code-only graph build (AST extraction + global clustering)."""
        return await self._run_and_measure(project_path, self._run_graphify_build)

    async def extract_only(self, project_path: str) -> BuildResult:
        """Fast update: AST extraction with clustering skipped (--no-cluster)."""
        return await self._run_and_measure(
            project_path, lambda p: self._run_graphify_build(p, cluster=False)
        )

    async def cluster_only(self, project_path: str) -> BuildResult:
        """Re-run global clustering on the existing graph (graphify cluster-only)."""
        return await self._run_and_measure(project_path, self._run_graphify_cluster)

    async def update_project(self, project_path: str, files: list[str]) -> BuildResult:
        """Deprecated alias kept for compatibility — a full build.

        The daemon now routes finding-driven updates through
        ``GraphUpdateCoordinator`` (see ``daemon/router.py``); this is retained
        only so external callers/tests referencing it keep working.
        """
        return await self.build_project(project_path)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_graph_engine.py -q`
Expected: PASS (new tests + the existing engine tests, including `test_build_uses_graphify_update_subcommand`).

- [ ] **Step 6: Commit**

```bash
git add daemon/models.py daemon/graph_engine.py tests/test_graph_engine.py
git commit -m "feat(graph): extract_only/cluster_only primitives + BuildResult.duration_s

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `GraphUpdateCoordinator`

**Files:**
- Create: `daemon/graph_update_coordinator.py`
- Test: `tests/test_graph_update_coordinator.py` (create)

**Interfaces:**
- Consumes (from Task 1): `GraphEngine.build_project/extract_only/cluster_only(path) -> BuildResult` with `.status` and `.duration_s`.
- Produces:
  - `GraphUpdateCoordinator(graph, on_updated, *, defer_threshold_s=5.0, min_interval_s=30.0, max_interval_s=300.0, cluster_debounce_s=60.0)`
  - `coordinator.record_full_build(project: str, duration_s: float) -> None`
  - `async coordinator.request_update(project: str, project_path: str) -> None` (non-blocking; schedules background work)
  - `on_updated` is `async (project: str, project_path: str, result: BuildResult) -> None`, invoked after every graph mutation.

**Design notes for the implementer:** `request_update` never awaits the build — it either marks the project `dirty` (busy/throttled) or calls `_start_run`, which flips `in_progress` synchronously and spawns `_run` as a background task. Trailing rebuilds (throttle/coalesce tail) use a single-pending `followup` task. The cluster debounce uses a **generation counter** (`cluster_gen`), not task cancellation, so a superseded debounce simply no-ops — nothing ever cancels a running graphify subprocess.

- [ ] **Step 1: Write the failing tests** — create `tests/test_graph_update_coordinator.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_graph_update_coordinator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.graph_update_coordinator'`.

- [ ] **Step 3: Create `daemon/graph_update_coordinator.py`:**

```python
"""Per-project graph-update scheduling for the Loom daemon.

A full ``graphify update`` re-extracts AND globally re-clusters a whole project.
Clustering is roughly half the build cost and grows superlinearly, so for
projects whose full build is slow this coordinator runs a fast extraction-only
update on the finding hot-path and defers the expensive clustering to a
debounced trailing pass. It also prevents overlapping rebuilds and throttles
adaptively based on how long a project takes to build. ``request_update``
returns immediately; graphify work runs in background tasks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from daemon.graph_engine import GraphEngine
from daemon.models import BuildResult

logger = logging.getLogger(__name__)

# A full build slower than this (seconds) puts a project into deferred-cluster mode.
DEFER_THRESHOLD_S = 5.0
# Adaptive throttle bounds (seconds): the interval scales with the last full build.
MIN_UPDATE_INTERVAL = 30.0
MAX_UPDATE_INTERVAL = 300.0
# Trailing delay before a deferred cluster pass runs; reset by each new extract.
CLUSTER_DEBOUNCE_S = 60.0

# Invoked after every graph mutation: (project, project_path, result).
OnUpdated = Callable[[str, str, BuildResult], Awaitable[None]]


@dataclass
class _ProjectState:
    last_full_build_s: float = 0.0   # drives the cost gate + adaptive interval
    last_extract_s: float = 0.0      # last extraction-only duration (deferred mode)
    in_progress: bool = False        # a graphify subprocess is running for this project
    dirty: bool = False              # a change arrived while busy/throttled
    last_run_ts: float = 0.0         # monotonic ts of the last run start
    followup_pending: bool = False   # a trailing rebuild task is queued
    cluster_gen: int = 0             # generation counter for the cluster debounce


class GraphUpdateCoordinator:
    def __init__(
        self,
        graph: GraphEngine,
        on_updated: OnUpdated,
        *,
        defer_threshold_s: float = DEFER_THRESHOLD_S,
        min_interval_s: float = MIN_UPDATE_INTERVAL,
        max_interval_s: float = MAX_UPDATE_INTERVAL,
        cluster_debounce_s: float = CLUSTER_DEBOUNCE_S,
    ):
        self.graph = graph
        self.on_updated = on_updated
        self.defer_threshold_s = defer_threshold_s
        self.min_interval_s = min_interval_s
        self.max_interval_s = max_interval_s
        self.cluster_debounce_s = cluster_debounce_s
        self._state: dict[str, _ProjectState] = {}

    def record_full_build(self, project: str, duration_s: float) -> None:
        """Seed the cost gate from an out-of-band full build (e.g. register)."""
        self._state.setdefault(project, _ProjectState()).last_full_build_s = duration_s

    def _interval(self, st: _ProjectState) -> float:
        return min(self.max_interval_s, max(self.min_interval_s, st.last_full_build_s))

    async def request_update(self, project: str, project_path: str) -> None:
        """Entry point per finding. Non-blocking: schedules background work."""
        st = self._state.setdefault(project, _ProjectState())
        now = time.monotonic()
        if st.in_progress:
            st.dirty = True                       # coalesce: rebuild after current run
            return
        if now - st.last_run_ts < self._interval(st):
            st.dirty = True                       # throttled: rebuild on the trailing edge
            self._arm_followup(project, project_path)
            return
        self._start_run(project, project_path, st, now)

    def _start_run(self, project: str, project_path: str, st: _ProjectState, now: float) -> None:
        st.in_progress = True
        st.dirty = False
        st.last_run_ts = now
        asyncio.create_task(self._run(project, project_path))

    async def _run(self, project: str, project_path: str) -> None:
        st = self._state[project]
        try:
            if st.last_full_build_s > self.defer_threshold_s:
                result = await self.graph.extract_only(project_path)
                if result.status == "completed":
                    st.last_extract_s = result.duration_s
                    self._arm_cluster(project, project_path)
            else:
                result = await self.graph.build_project(project_path)
                if result.status == "completed":
                    st.last_full_build_s = result.duration_s
            await self.on_updated(project, project_path, result)
        except Exception as exc:                  # never let a build wedge the project
            logger.warning("graph update failed for %s: %s", project, exc)
        finally:
            st.in_progress = False
        if st.dirty:
            self._arm_followup(project, project_path)

    def _arm_followup(self, project: str, project_path: str) -> None:
        st = self._state[project]
        if st.followup_pending:
            return                                # one trailing rebuild pending is enough
        st.followup_pending = True
        asyncio.create_task(self._followup_fire(project, project_path))

    async def _followup_fire(self, project: str, project_path: str) -> None:
        st = self._state[project]
        delay = max(0.0, self._interval(st) - (time.monotonic() - st.last_run_ts))
        await asyncio.sleep(delay)
        st.followup_pending = False
        if st.dirty and not st.in_progress:
            self._start_run(project, project_path, st, time.monotonic())

    def _arm_cluster(self, project: str, project_path: str) -> None:
        st = self._state[project]
        st.cluster_gen += 1
        asyncio.create_task(self._cluster_fire(project, project_path, st.cluster_gen))

    async def _cluster_fire(self, project: str, project_path: str, gen: int) -> None:
        await asyncio.sleep(self.cluster_debounce_s)
        st = self._state[project]
        if gen != st.cluster_gen:
            return                                # superseded by a newer extract
        if st.in_progress:
            self._arm_cluster(project, project_path)   # re-debounce after the current op
            return
        st.in_progress = True
        try:
            result = await self.graph.cluster_only(project_path)
            if result.status == "completed":
                st.last_full_build_s = st.last_extract_s + result.duration_s
            await self.on_updated(project, project_path, result)
        except Exception as exc:
            logger.warning("cluster pass failed for %s: %s", project, exc)
        finally:
            st.in_progress = False
        if st.dirty:
            self._arm_followup(project, project_path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_graph_update_coordinator.py -q`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add daemon/graph_update_coordinator.py tests/test_graph_update_coordinator.py
git commit -m "feat(graph): GraphUpdateCoordinator — cost-gated cluster deferral + overlap guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Router delegates finding-updates to the coordinator

**Files:**
- Modify: `daemon/router.py` (`__init__`, `_handle_finding`, `_build_project`; remove `_can_update`, `_last_update`, `_update_project`; add `_on_graph_updated`)
- Test: `tests/test_router.py` (extend)

**Interfaces:**
- Consumes (from Task 2): `GraphUpdateCoordinator(graph, on_updated, ...)`, `.record_full_build(project, duration_s)`, `async .request_update(project, project_path)`.
- Produces: `Router.coordinator` attribute; `async Router._on_graph_updated(project, project_path, result)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_router.py`:

```python
@pytest.mark.asyncio
async def test_finding_delegates_to_coordinator(router_with_registry, monkeypatch):
    """A finding that references code files calls coordinator.request_update."""
    router, reg, engine, tmp_path = router_with_registry
    await reg.upsert_project("test-proj", str(tmp_path / "repo"))

    calls = []

    async def fake_request_update(project, project_path):
        calls.append((project, project_path))

    monkeypatch.setattr(router.coordinator, "request_update", fake_request_update)

    inbox = tmp_path / "inbox" / "test-proj"
    inbox.mkdir(parents=True)
    finding = inbox / "finding-x.md"
    finding.write_text(
        "---\nagent: a\nproject: test-proj\ntype: bug\nfiles: [daemon/x.py]\n---\nbody"
    )

    await router.handle_file("test-proj", str(finding))

    assert calls == [("test-proj", str(tmp_path / "repo"))]


@pytest.mark.asyncio
async def test_register_seeds_the_cost_gate(router_with_registry, monkeypatch):
    """The initial register-time build seeds the coordinator's cost gate."""
    router, reg, engine, tmp_path = router_with_registry
    from daemon.models import BuildResult

    async def fake_build(path):
        return BuildResult(project="p", status="completed", nodes=1, edges=1, duration_s=7.5)

    async def noop(*a, **k):
        return None

    seeded = []
    monkeypatch.setattr(engine, "build_project", fake_build)
    monkeypatch.setattr(router, "_scan_and_share", noop)
    monkeypatch.setattr(
        router.coordinator, "record_full_build",
        lambda project, dur: seeded.append((project, dur)),
    )

    await router._build_project("test-proj", str(tmp_path / "repo"))

    assert seeded == [("test-proj", 7.5)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_router.py -q -k "delegates_to_coordinator or seeds_the_cost_gate"`
Expected: FAIL — `AttributeError: 'Router' object has no attribute 'coordinator'`.

- [ ] **Step 3: Wire the coordinator into `daemon/router.py`.**

3a. Add the import near the other daemon imports:

```python
from daemon.graph_update_coordinator import GraphUpdateCoordinator
```

3b. In `Router.__init__`, after `self.recall = recall` (and the other assignments), add the coordinator and drop the old per-project timestamp map. Replace:

```python
        self._last_update: dict[str, float] = {}  # project -> timestamp
        self._event_queue: asyncio.Queue[WsEvent] = asyncio.Queue()
```

with:

```python
        self._event_queue: asyncio.Queue[WsEvent] = asyncio.Queue()
        self.coordinator = GraphUpdateCoordinator(graph_engine, self._on_graph_updated)
```

3c. In `_handle_finding`, replace the update-trigger block:

```python
        # If finding references code files, queue incremental update
        if frontmatter.files and self._can_update(project):
            project_info = await self.registry.get_project(project)
            if project_info:
                asyncio.create_task(
                    self._update_project(project, project_info.project_path, frontmatter)
                )
```

with:

```python
        # If the finding references code files, hand the update to the
        # coordinator (cost-gated cluster deferral + overlap guard + throttle).
        if frontmatter.files:
            project_info = await self.registry.get_project(project)
            if project_info:
                await self.coordinator.request_update(project, project_info.project_path)
```

3d. **Delete** the now-unused `_can_update` method and the entire `_update_project` method. **Add** `_on_graph_updated` in their place (this is the old `_update_project` tail, minus the graphify call):

```python
    async def _on_graph_updated(self, project: str, project_path: str, result: "BuildResult"):
        """Callback for the coordinator: persist stats, emit event, refresh context."""
        communities = 0
        if result.status == "completed":
            stats = await self.graph.get_stats(project_path)
            communities = stats.communities
            await self.registry.update_graph_stats(
                project, result.nodes, result.edges, communities
            )
        await self._emit_event("graph:updated", project, {
            "nodes_added": result.nodes,
            "edges_added": result.edges,
            "communities": communities,
            "status": result.status,
            "error": result.error,
        })
        await self._regenerate_shared_context(project, project_path)
```

Add `BuildResult` to the existing `from daemon.models import (...)` block so the annotation resolves.

3e. In `_build_project`, seed the gate after the build completes. After the existing `await self.registry.update_graph_stats(...)` call (inside `if result.status == "completed":`), add:

```python
        self.coordinator.record_full_build(project, result.duration_s)
```

- [ ] **Step 4: Run the router tests, then the full suite**

Run: `.venv/bin/python -m pytest tests/test_router.py -q`
Expected: PASS (new tests + existing router tests).

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — baseline green (no regressions). Watch specifically for any existing test that referenced `Router._can_update` / `_update_project`; if one exists, update it to drive `coordinator.request_update` instead (report it if found).

- [ ] **Step 5: Commit**

```bash
git add daemon/router.py tests/test_router.py
git commit -m "feat(router): route finding-driven graph updates through GraphUpdateCoordinator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Behavior change to expect (intended):** for a *deferred* (slow-building) project, a finding burst now emits `graph:updated` twice — once after the fast extract (communities temporarily 0) and once after the trailing cluster pass. Normal (fast) projects are unchanged: one emit per update. This matches the spec's data-flow.
- **Dropped field (intended):** the `graph:updated` event no longer carries the `agent` field on finding-driven updates (updates are coalesced across findings, so single-agent attribution is no longer meaningful). The initial register-time build never carried it either.
- **Do not** add graceful cluster-task cancellation on shutdown or community-preservation during the deferred window — both are explicitly out of scope (spec §Scope/YAGNI).
