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
        if st.in_progress:
            # Defensive: callers already check `not in_progress`, so this is
            # unreachable today. Guard anyway so a future refactor that adds an
            # await before a `_start_run` call can never launch a 2nd concurrent
            # graphify subprocess — it coalesces into the running run instead.
            st.dirty = True
            return
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
        # If dirty but a run/cluster is in_progress, we deliberately do NOT
        # re-arm here (that would busy-loop with delay=0). The in-flight op's
        # own tail (`if st.dirty: _arm_followup`) re-arms once it completes;
        # test_no_second_subprocess_while_cluster_runs asserts that recovery.

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
