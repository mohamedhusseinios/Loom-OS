# Cost-Gated Cluster-Deferral for the Daemon Graph-Update Path — Design

- **Date:** 2026-07-03
- **Status:** Approved (brainstorming), pending implementation plan
- **Feature:** Loom "next-moat" roadmap Feature #3 (incremental graph persistence) — **pragmatic reinterpretation**
- **Branch:** `loom/graph-cluster-deferral` (off `main`)

## Context & problem

Feature #3 was originally specified as *incremental graph persistence* — re-extract only changed files and merge into the graph. A 2026-07-03 spike proved that approach is **non-viable** on graphify 0.8.47: subtree re-extraction uses extraction-root-relative node IDs (so `merge-graphs` can't match nodes and unions duplicates, +45%/update), union-merge can't delete stale nodes, and community IDs drift — none caught by `graphify diagnose multigraph`. (See memory `loom-feature3-incremental-spike` and the roadmap's ❌-dropped Feature #3.)

However, the spike also established the **real, addressable cost**: every finding-triggered update runs `graphify update <whole_project>` (a full re-extract + global cluster), and **clustering is ~50% of build time at 200 files and grows superlinearly** (b≈1.1 by 3000 files; a 10K–20K-file repo extrapolates to ~3.5–8 min). Two concrete problems in the current code:

1. **No incrementality of the expensive phase.** `GraphEngine.update_project(path, files)` ignores `files` and calls `build_project` → a full extract **and** cluster every time.
2. **Overlap bug.** `Router._can_update` throttles by time only (`MIN_UPDATE_INTERVAL=30s`) with **no in-progress guard** — if a build takes >30s, a second concurrent `graphify` subprocess can start.

## Goal & non-goals

**Goal.** Reduce per-update cost on large repos by deferring the expensive **global clustering** off the finding-triggered hot path, without changing behavior for normal (fast-building) repos, and eliminate overlapping/redundant rebuilds.

**Non-goals.** Incremental *extraction* / graph merging (spike-killed). Preserving community assignments during the deferred window (accepted gap — see Scope). Graceful cancellation of pending cluster tasks on daemon shutdown (v1 abandons them).

## Design overview

Three parts: (1) `GraphEngine` gains cluster-aware primitives + build-duration measurement; (2) a new, unit-testable `GraphUpdateCoordinator` owns per-project update policy (cost-gated deferral, overlap coalescing, adaptive throttling, trailing cluster passes); (3) `Router` is thinned to delegate to the coordinator.

**Cost gate:** a project whose last full build exceeded `DEFER_THRESHOLD_S` runs in **deferred mode** (fast `--no-cluster` extract on findings + a trailing debounced `cluster-only`); otherwise it keeps today's **inline** full build. Normal repos are unchanged.

## Component 1 — `GraphEngine` primitives + duration (`daemon/graph_engine.py`, `daemon/models.py`)

- `_run_graphify_build(path, cluster: bool = True)` — appends `--no-cluster` to the `graphify update` argv when `cluster=False`. Stub-creation and error handling unchanged.
- `build_project(path) -> BuildResult` — unchanged semantics (full extract + cluster); now measures and reports wall-time.
- **New** `extract_only(path) -> BuildResult` — `graphify update <path> --no-cluster` (fast path). Same stub/error handling as `build_project`.
- **New** `cluster_only(path) -> BuildResult` — `graphify cluster-only <path> --no-viz` (trailing pass; reads the existing graph.json and writes community assignments back).
- **`models.py`:** add `duration_s: float = 0.0` to `BuildResult`; each of the three methods populates it (wall-time around the `asyncio.to_thread` subprocess call).

## Component 2 — `GraphUpdateCoordinator` (`daemon/graph_update_coordinator.py`, new)

One well-bounded unit; depends only on a `GraphEngine` and an `on_updated` callback; unit-testable with a fake engine (no real graphify). Per-project state:

```
last_full_build_s: float   # drives the cost gate; ≈ true extract+cluster cost
in_progress: bool          # a graphify subprocess is running for this project
dirty: bool                # a change arrived while in_progress (coalesce)
last_run_ts: float         # for the adaptive throttle
cluster_task: asyncio.Task | None   # pending trailing cluster (debounce)
```

Public surface:
- `record_full_build(project, duration_s)` — seeds/updates the gate metric (called by the register-time initial build).
- `async request_update(project, path, files)` — the single entry point per finding:
  - **Gate:** `deferred = last_full_build_s > DEFER_THRESHOLD_S`.
  - **Overlap guard / coalesce:** if `in_progress`, set `dirty = True`, return. When the running build finishes, if `dirty`, run exactly one more. Never two concurrent graphify subprocesses per project.
  - **Adaptive throttle:** effective interval = `clamp(last_full_build_s, MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL)`. If within the interval, set `dirty` + arm a trailing timer so the pending change still builds when the interval elapses (no lost updates, no lost-wakeup).
  - **Run:** not deferred → `build_project` (inline full); deferred → `extract_only`, then (re)arm the trailing cluster debounce. Always run the `on_updated` tail (update stats, emit `graph:updated`, regenerate shared context).
  - **Trailing cluster debounce:** each deferred extract cancels+recreates a `CLUSTER_DEBOUNCE_S` timer; when it fires (and the project is not `in_progress`), run `cluster_only`, run `on_updated` again, and set `last_full_build_s ≈ last_extract_s + last_cluster_s` (keeps the gate ≈ true full cost). If a burst keeps arriving, the timer keeps resetting → clustering runs once, after the burst settles.

## Component 3 — Router integration (`daemon/router.py`)

- Construct a `GraphUpdateCoordinator(graph_engine, on_updated=<the current _update_project tail>)` in `Router.__init__`.
- `_handle_finding`: replace the inline `if frontmatter.files and self._can_update(...)` + `create_task(_update_project(...))` block with `await self.coordinator.request_update(project, project_info.project_path, frontmatter.files)`. `_can_update` / `_last_update` move into the coordinator.
- `_build_project` (register-time initial full build): after it completes, call `coordinator.record_full_build(project, result.duration_s)` to seed the gate before findings arrive.
- The "update `graph_stats` → emit `graph:updated` → `_regenerate_shared_context`" tail becomes the coordinator's `on_updated` callback — behavior unchanged.

## Data flow (deferred repo, during a finding burst)

```
finding → request_update → extract_only (fast)
        → on_updated: emit graph:updated  (nodes/edges fresh, communities = 0)
        → arm cluster timer
   …more findings reset the timer…
   …burst settles…
        → cluster_only → on_updated: emit graph:updated  (communities populated)
```

Two `graph:updated` emits per burst for deferred repos: the dashboard shows fresh nodes/edges immediately, communities after the burst settles. Non-deferred repos: one emit per update, exactly as today.

## Config (module constants, mirroring today's `MIN_UPDATE_INTERVAL`)

| Constant | Default | Meaning |
|---|---|---|
| `DEFER_THRESHOLD_S` | 5 | full build slower than this → project enters deferred mode |
| `MIN_UPDATE_INTERVAL` | 30 | floor for the adaptive throttle (unchanged from today) |
| `MAX_UPDATE_INTERVAL` | 300 | cap for the adaptive throttle |
| `CLUSTER_DEBOUNCE_S` | 60 | trailing delay before a deferred cluster pass runs |

## Error handling

- Every graphify call wrapped (as today) → `BuildResult(status="failed", error=...)`. A `finally` block always clears `in_progress`, so a failed/timed-out build cannot wedge a project.
- Failed `extract_only` → no cluster scheduled that cycle. Failed `cluster_only` → logged + emitted, does not crash the loop.
- Subprocess `timeout=300` unchanged.
- Pending cluster tasks are abandoned on daemon shutdown (acceptable v1).

## Testing strategy (TDD)

- **`GraphUpdateCoordinator`** with a **fake `GraphEngine`** (records calls, returns configurable `duration_s`), injecting small interval/debounce values so tests never sleep for real:
  - gating: fast last-build → inline `build_project`; slow last-build → `extract_only` + a scheduled `cluster_only`.
  - coalescing: a finding during an in-progress build → exactly one follow-up build, no concurrency.
  - adaptive throttle: builds no more often than `clamp(last_full_build_s, …)`; a throttled change still eventually builds.
  - debounce: N rapid extracts → exactly one `cluster_only`, after settle.
  - error path: a failed build clears `in_progress` (no wedge) and schedules no cluster.
- **`GraphEngine`**: in `tests/test_graph_engine.py` (create if absent), mock `subprocess.run`; assert argv carries `--no-cluster` (extract_only) and `cluster-only … --no-viz` (cluster_only); assert `duration_s` is populated.
- **`Router`**: `_handle_finding` delegates to `coordinator.request_update`; register seeds the gate via `record_full_build`. Follow the module-global test-mode pattern in `tests/test_api.py`.
- Baseline suite stays green; each new module gets its `tests/test_<module>.py`.

## Scope / YAGNI

**In:** the three components above. **Deliberately out:** incremental extraction / graph merging (spike-killed); preserving communities during the deferred window (accept the empty gap — the cost gate confines it to large repos where it's justified); graceful cluster-task cancellation on shutdown.

## References

- Spike results: merge-based incremental is non-viable → memory `loom-feature3-incremental-spike`; earlier drop → `graphify-no-incremental-update`.
- Roadmap: `docs/plans/2026-07-01-loom-next-moat-roadmap-implementation.md` (Feature #3, ❌ dropped — this is the pragmatic reinterpretation of its goal).
- Touch points: `daemon/graph_engine.py` (`update_project`, `_run_graphify_build`, `build_project`), `daemon/router.py` (`_handle_finding`, `_can_update`, `_update_project`, `_build_project`), `daemon/models.py` (`BuildResult`).

## Known limitation (follow-up)

The "never two concurrent graphify subprocesses per project" invariant holds for **coordinator-mediated (finding-driven)** updates. The register-time initial full build (`_handle_register` → `_build_project`) runs **outside** the coordinator (pre-existing behavior), so a finding arriving during a large repo's initial build can still start a concurrent `graphify` build. Routing the register build through the coordinator — or setting an in-progress marker before launching it so an early finding coalesces — is a tracked follow-up, not addressed in this change.
