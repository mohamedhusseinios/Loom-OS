# Phase 2 · Feature #4 — First-Gen Module Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
> **Parent plan:** [docs/plans/2026-07-01-loom-next-moat-roadmap-implementation.md](2026-07-01-loom-next-moat-roadmap-implementation.md) — Phase 2, Feature #4.

**Goal:** Move the five first-generation in-memory modules (`temporal`, `traces`, `sessions`, `snapshots`, `patterns`) from "present" to "battle-tested" by adding edge-case tests and targeted robustness fixes — **grounded in the actual code**, not a generic checklist.

**Architecture:** Each module is a self-contained in-memory manager class in `daemon/`, each with an existing `tests/test_<module>.py`. Hardening = extend the existing test file + a small, surgical change to the module. No new modules, no new deps, no API changes.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode=auto`). Run tests with `.venv/bin/python -m pytest` (bare `pytest` can't collect `tests/test_benchmarks.py` — pre-existing packaging gap).

## Global Constraints

- **Evidence over checklist.** `plan-inputs.md` prescribed `asyncio.Lock` around mutating methods. **Do NOT add those locks** — `record`/`expire`/`start_span`/`_evict_oldest`/`capture`/`observe` have **no `await` in their critical sections**, so in single-threaded asyncio they already run atomically; a lock adds no protection and real overhead. Only guard the ONE place with a genuine await-induced race: `sessions.end_session` (mutates then `await`s `_bridge_to_inbox`).
- **Behavior-preserving unless fixing a stated bug.** The only intentional behavior CHANGE is the `patterns` deprecate-resurrection fix (Task 5). Everything else preserves current outputs; new tests characterize/lock existing behavior or add guards for failure paths.
- **No scope creep.** Do NOT expand `patterns._normalise` with stemming/abbreviations — that changes dedup semantics and needs a dependency; it's a separate future task.
- **Tests:** `.venv/bin/python -m pytest tests/ -q` stays green (baseline **249 passed, 8 pre-existing warnings**). Each task extends the module's existing `tests/test_<module>.py`.
- **Commits:** conventional; `git add <specific files>` only (never `-A`/`-am`); end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

| Module | File | Change | Test file |
|--------|------|--------|-----------|
| Temporal | `daemon/temporal.py` | characterization tests only (behavior already correct) | `tests/test_temporal.py` |
| Traces | `daemon/traces.py` | idempotent `finish_span` + clamp `max_spans>=1` | `tests/test_traces.py` |
| Sessions | `daemon/sessions.py` | guard `_bridge_to_inbox` I/O + idempotent `end_session` | `tests/test_sessions.py` |
| Snapshots | `daemon/snapshots.py` | clamp `max_snapshots>=1` + edge tests | `tests/test_snapshots.py` |
| Patterns | `daemon/patterns.py` | **fix deprecate-resurrection bug** | `tests/test_patterns.py` |

---

### Task 1: Temporal — `facts_at` boundary characterization

**Files:** Test: `tests/test_temporal.py` (extend). No code change expected (behavior verified correct; if a test fails, that's a real bug to fix).

**Interfaces:** `TemporalTracker()`; `await record(fact_text, project, agent_id, valid_from=None) -> TemporalFact`; `await expire(fact_id, reason="") -> TemporalFact|None`; `await facts_at(project, at_time: str) -> list[TemporalFact]`. `facts_at` includes a fact when `valid_from <= at_time` AND (`valid_to is None` OR `valid_to >= at_time`) — both bounds **inclusive**.

- [ ] **Step 1: Write the characterization tests**

```python
# Add to tests/test_temporal.py
import pytest
from daemon.temporal import TemporalTracker


@pytest.mark.asyncio
async def test_facts_at_boundaries_are_inclusive():
    t = TemporalTracker()
    f = await t.record("auth uses bcrypt", "p", "a1", valid_from="2026-01-01T00:00:00")
    # exactly valid_from → included (inclusive start)
    assert f.id in {x.id for x in await t.facts_at("p", "2026-01-01T00:00:00")}
    # before valid_from → excluded
    assert f.id not in {x.id for x in await t.facts_at("p", "2025-12-31T23:59:59")}
    # open-ended (valid_to=None) → active at any later time
    assert f.id in {x.id for x in await t.facts_at("p", "2030-01-01T00:00:00")}


@pytest.mark.asyncio
async def test_facts_at_excludes_after_expiry_but_includes_expiry_instant():
    t = TemporalTracker()
    f = await t.record("x", "p", "a1", valid_from="2026-01-01T00:00:00")
    await t.expire(f.id, reason="changed")   # sets valid_to = now (future vs valid_from)
    vt = (await t.get_fact(f.id)).valid_to
    # at exactly valid_to → still included (inclusive end)
    assert f.id in {x.id for x in await t.facts_at("p", vt)}
    # strictly after valid_to → excluded
    assert f.id not in {x.id for x in await t.facts_at("p", "2099-01-01T00:00:00")}
```

- [ ] **Step 2: Run — expected PASS (characterization)**

Run: `.venv/bin/python -m pytest tests/test_temporal.py -v`
Expected: PASS. If either FAILS, `facts_at` has a real boundary bug — fix it in `daemon/temporal.py` (adjust the `>`/`<` comparisons) and note it in the report.

- [ ] **Step 3: Commit**

```bash
git add tests/test_temporal.py
git commit -m "test(temporal): lock facts_at inclusive-boundary semantics"
```

---

### Task 2: Traces — idempotent `finish_span` + eviction robustness

**Files:** Modify: `daemon/traces.py`. Test: `tests/test_traces.py` (extend).

**Interfaces:** `TraceCapture(max_spans=10000)`; `await start_span(name, kind: SpanKind, project, agent_id, parent_id=None, input_data=None) -> TraceSpan`; `await finish_span(span_id, output_data=None, metadata=None, error=None) -> None`. `TraceSpan.end_time` is `None` until finished. Currently `finish_span` re-finalizes on repeat calls (recomputes `latency_ms`); `_evict_oldest` pops while `len(_spans) > _max_spans`.

- [ ] **Step 1: Write the failing test (idempotency)**

```python
# Add to tests/test_traces.py
import pytest
from daemon.traces import TraceCapture, SpanKind


@pytest.mark.asyncio
async def test_finish_span_is_idempotent():
    cap = TraceCapture()
    span = await cap.start_span("t", SpanKind.TOOL, "p", "a1")
    await cap.finish_span(span.id, output_data={"n": 1})
    first_latency = span.latency_ms
    first_output = span.output_data
    # second finish must be a no-op (don't overwrite latency/output)
    await cap.finish_span(span.id, output_data={"n": 2})
    assert span.latency_ms == first_latency
    assert span.output_data == first_output


@pytest.mark.asyncio
async def test_eviction_clamps_and_keeps_newest():
    cap = TraceCapture(max_spans=0)          # must clamp to >=1, not self-evict
    s = await cap.start_span("t", SpanKind.TOOL, "p", "a1")
    assert (await cap.get_spans(project="p"))[0].id == s.id   # retained
    cap2 = TraceCapture(max_spans=2)
    ids = [(await cap2.start_span(f"s{i}", SpanKind.TOOL, "p", "a1")).id for i in range(3)]
    kept = {sp.id for sp in await cap2.get_spans(project="p")}
    assert kept == set(ids[1:])              # only the newest 2, oldest evicted
    assert ids[0] not in cap2._by_id         # _by_id stays in sync (no orphan)
```

- [ ] **Step 2: Run — verify it fails**

Run: `.venv/bin/python -m pytest tests/test_traces.py -k "idempotent or clamps" -v`
Expected: FAIL — `test_finish_span_is_idempotent` fails (latency recomputed); `test_eviction_clamps_and_keeps_newest` fails on `max_spans=0` (span self-evicted, `get_spans` empty → IndexError).

- [ ] **Step 3: Implement the guards**

```python
# daemon/traces.py — in __init__, clamp max_spans:
        self._max_spans = max(1, max_spans)

# daemon/traces.py — at the top of finish_span, after the None check:
        if span.end_time is not None:
            return  # already finished — idempotent no-op
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_traces.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add daemon/traces.py tests/test_traces.py
git commit -m "fix(traces): idempotent finish_span + clamp max_spans>=1"
```

---

### Task 3: Sessions — guard `_bridge_to_inbox` I/O + idempotent `end_session`

**Files:** Modify: `daemon/sessions.py`. Test: `tests/test_sessions.py` (extend).

**Interfaces:** `SessionManager(base_dir="~/.loom")`; `await start_session(agent_id, project) -> Session`; `await add_context(session_id, key, value)`; `await end_session(session_id) -> None`. `end_session` sets `session.active = False` then `await self._bridge_to_inbox(session)`, which `mkdir`s and `write_text`s one `finding-*.md` per non-`_`-prefixed context item.

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_sessions.py
import pytest
from daemon.sessions import SessionManager


@pytest.mark.asyncio
async def test_end_session_survives_write_failure(tmp_path, monkeypatch):
    mgr = SessionManager(base_dir=str(tmp_path))
    s = await mgr.start_session("a1", "p")
    await mgr.add_context(s.id, "learning", "auth uses bcrypt")

    from pathlib import Path
    def boom(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", boom)
    # A mailbox write failure must NOT crash session close.
    await mgr.end_session(s.id)
    assert (await mgr.get_session(s.id)).active is False


@pytest.mark.asyncio
async def test_end_session_is_idempotent(tmp_path):
    mgr = SessionManager(base_dir=str(tmp_path))
    s = await mgr.start_session("a1", "p")
    await mgr.add_context(s.id, "k", "v")
    await mgr.end_session(s.id)
    inbox = tmp_path / "inbox" / "p"
    after_first = sorted(inbox.glob("finding-*.md"))
    await mgr.end_session(s.id)               # second close must not re-bridge
    after_second = sorted(inbox.glob("finding-*.md"))
    assert after_first == after_second and len(after_first) == 1
```

- [ ] **Step 2: Run — verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sessions.py -k "write_failure or idempotent" -v`
Expected: FAIL — `test_end_session_survives_write_failure` raises `OSError` out of `end_session`; `test_end_session_is_idempotent` finds 2 findings (double-bridge).

- [ ] **Step 3: Implement the guards**

```python
# daemon/sessions.py — early-return in end_session BEFORE mutating (idempotent close):
    async def end_session(self, session_id: str) -> None:
        """Mark a session as inactive and bridge learnings to permanent inbox."""
        session = self._sessions.get(session_id)
        if session is None:
            logger.warning("end_session called for unknown id: %s", session_id)
            return
        if not session.active:
            return  # already closed — don't re-bridge
        session.active = False
        if session.context:
            await self._bridge_to_inbox(session)
```

```python
# daemon/sessions.py — wrap the per-item write in _bridge_to_inbox so one bad
# write doesn't abort the close. Replace the write_text call site:
            try:
                finding_path.write_text(
                    f"""---
agent: {session.agent_id}
project: {session.project}
session: {session.id}
timestamp: {datetime.now(timezone.utc).isoformat()}
confidence: medium
key: {key}
---
{value}
"""
                )
                persisted += 1
            except OSError as exc:
                logger.warning(
                    "Session %s: failed to bridge context item %r: %s",
                    session.id, key, exc,
                )
```

(Also wrap the `inbox.mkdir(parents=True, exist_ok=True)` in the same try or a guarding try/except so a mkdir failure is logged and returns early rather than raising.)

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_sessions.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add daemon/sessions.py tests/test_sessions.py
git commit -m "fix(sessions): survive inbox write failures + idempotent end_session"
```

---

### Task 4: Snapshots — clamp `max_snapshots` + eviction/replay edge tests

**Files:** Modify: `daemon/snapshots.py`. Test: `tests/test_snapshots.py` (extend).

**Interfaces:** `SnapshotManager(max_snapshots=200)`; `await capture(project, agent_id, step, activity="", context_summary="", graph_nodes_added=0, graph_edges_added=0) -> StateSnapshot`; `await replay(project, agent_id=None, limit=50) -> list[StateSnapshot]` (chronological). Per-key ring buffer capped at `_max`.

- [ ] **Step 1: Write the failing/edge tests**

```python
# Add to tests/test_snapshots.py
import pytest
from daemon.snapshots import SnapshotManager


@pytest.mark.asyncio
async def test_capture_clamps_max_and_keeps_newest():
    mgr = SnapshotManager(max_snapshots=0)     # must clamp to >=1
    s = await mgr.capture("p", "a1", step=1)
    assert [x.id for x in await mgr.replay("p", "a1")] == [s.id]   # retained
    mgr2 = SnapshotManager(max_snapshots=2)
    for i in range(3):
        await mgr2.capture("p", "a1", step=i)
    steps = [x.step for x in await mgr2.replay("p", "a1")]
    assert steps == [1, 2]                       # oldest (step 0) evicted, newest kept


@pytest.mark.asyncio
async def test_replay_empty_returns_empty_list():
    mgr = SnapshotManager()
    assert await mgr.replay("nope", "nobody") == []
```

- [ ] **Step 2: Run — verify it fails**

Run: `.venv/bin/python -m pytest tests/test_snapshots.py -k "clamps or empty" -v`
Expected: FAIL — `test_capture_clamps_max_and_keeps_newest` fails on `max_snapshots=0` (snapshot self-evicted, replay empty).

- [ ] **Step 3: Implement the clamp**

```python
# daemon/snapshots.py — in __init__:
        self._max = max(1, max_snapshots)
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_snapshots.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add daemon/snapshots.py tests/test_snapshots.py
git commit -m "fix(snapshots): clamp max_snapshots>=1 + replay edge coverage"
```

---

### Task 5: Patterns — fix deprecate-resurrection bug + lifecycle tests

**Files:** Modify: `daemon/patterns.py`. Test: `tests/test_patterns.py` (extend).

**Interfaces:** `PatternRepository()`; `await observe(pattern_text, project, agent_id, kind="PATTERN") -> Pattern`; `await deprecate(pattern_id, reason="") -> Pattern|None`; `await cross_project_patterns() -> list[Pattern]`. `Pattern.status: PatternStatus` (CANDIDATE/VERIFIED/ESTABLISHED/DEPRECATED). **Bug:** `observe()` on an existing pattern calls `self._compute_status(pattern)`, which never returns DEPRECATED — so re-observing a deprecated pattern silently un-deprecates it.

- [ ] **Step 1: Write the failing test (the bug) + lifecycle tests**

```python
# Add to tests/test_patterns.py
import pytest
from daemon.patterns import PatternRepository, PatternStatus


@pytest.mark.asyncio
async def test_observing_a_deprecated_pattern_does_not_resurrect_it():
    repo = PatternRepository()
    p = await repo.observe("use dependency injection", "p1", "a1")
    await repo.deprecate(p.id, reason="superseded")
    # same normalised text, observed again → must STAY deprecated
    again = await repo.observe("Use dependency injection.", "p2", "a2")
    assert again.id == p.id
    assert again.status == PatternStatus.DEPRECATED


@pytest.mark.asyncio
async def test_cross_project_dedup_counts_one_pattern_two_projects():
    repo = PatternRepository()
    await repo.observe("retry with backoff", "p1", "a1")
    await repo.observe("  Retry   with backoff  ", "p2", "a2")  # same after normalise
    cross = await repo.cross_project_patterns()
    assert len(cross) == 1
    assert cross[0].projects == {"p1", "p2"}
```

- [ ] **Step 2: Run — verify it fails**

Run: `.venv/bin/python -m pytest tests/test_patterns.py -k "resurrect or dedup" -v`
Expected: FAIL — `test_observing_a_deprecated_pattern_does_not_resurrect_it` fails (status flips back to CANDIDATE). Dedup test should PASS (confirms normalise dedup already works).

- [ ] **Step 3: Fix the bug**

```python
# daemon/patterns.py — in observe(), guard the update block so a DEPRECATED
# pattern is not resurrected. Replace the "Update existing" section:
        # Update existing
        pattern.observation_count += 1
        pattern.projects.add(project)
        pattern.agents.add(agent_id)
        pattern.last_seen = datetime.now(timezone.utc).isoformat()

        # A manually deprecated pattern stays deprecated — re-observation must
        # not silently promote it back into the active lifecycle.
        if pattern.status != PatternStatus.DEPRECATED:
            pattern.confidence = self._compute_confidence(pattern)
            pattern.status = self._compute_status(pattern)

        return pattern
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/python -m pytest tests/test_patterns.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add daemon/patterns.py tests/test_patterns.py
git commit -m "fix(patterns): re-observing a deprecated pattern no longer resurrects it"
```

---

## Self-Review

- **Coverage:** all 5 modules touched (temporal characterization; traces idempotency+clamp; sessions I/O guard+idempotent close; snapshots clamp; patterns bug fix). ✅
- **No no-op locks:** confirmed no `asyncio.Lock` added — justified in Global Constraints (no `await` in the mutating critical sections). ✅
- **Type/signature consistency:** every test uses the real signatures read from source (`record(fact_text, project, agent_id, valid_from=)`, `start_span(name, kind, project, agent_id, ...)`, `capture(project, agent_id, step, ...)`, `observe(pattern_text, project, agent_id, ...)`). ✅
- **One intentional behavior change** (patterns resurrection) — flagged; everything else preserves outputs. ✅

## Execution Handoff

Execute via **superpowers:subagent-driven-development** — one implementer per task (Tasks 1–5 are independent modules), a task review after each, and a whole-branch review at the end. Tasks 3 (sessions I/O) and 5 (patterns bug) are the highest-value; Task 1 (temporal) is characterization-only and may pass without a code change.
