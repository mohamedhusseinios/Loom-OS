"""Tests for the TemporalTracker."""
import pytest
from daemon.temporal import TemporalTracker, TemporalFact


@pytest.fixture
def tracker():
    return TemporalTracker()


@pytest.mark.asyncio
async def test_record_fact(tracker):
    """Recording a fact stores it with valid_from/valid_to."""
    fact = await tracker.record(
        fact_text="auth.py uses bcrypt for password hashing",
        project="proj",
        agent_id="agent-1",
    )
    assert fact.id
    assert fact.fact_text == "auth.py uses bcrypt for password hashing"
    assert fact.valid_from is not None
    assert fact.valid_to is None  # still true
    assert fact.active is True


@pytest.mark.asyncio
async def test_expire_fact(tracker):
    """Expiring a fact sets valid_to and marks it inactive."""
    fact = await tracker.record("password policy: min 8 chars", "proj", "a1")
    await tracker.expire(fact.id, reason="policy changed to 12 chars")

    expired = await tracker.get_fact(fact.id)
    assert expired.active is False
    assert expired.valid_to is not None
    assert "policy changed" in expired.expire_reason


@pytest.mark.asyncio
async def test_facts_active_at_time(tracker):
    """Active facts at a given time exclude expired ones."""
    await tracker.record("fact A: uses old API", "proj", "a1")
    fact_b = await tracker.record("fact B: uses new API", "proj", "a1")
    await tracker.expire(fact_b.id)

    active = await tracker.active_facts(project="proj")
    assert len(active) == 1
    assert active[0].fact_text == "fact A: uses old API"


@pytest.mark.asyncio
async def test_facts_filtered_by_project(tracker):
    """Facts are isolated per project."""
    await tracker.record("proj-a fact", "proj-a", "a1")
    await tracker.record("proj-b fact", "proj-b", "a1")

    facts = await tracker.active_facts(project="proj-a")
    assert len(facts) == 1
    assert facts[0].project == "proj-a"


@pytest.mark.asyncio
async def test_get_fact_nonexistent(tracker):
    """Looking up nonexistent fact returns None."""
    assert await tracker.get_fact("nonexistent") is None


@pytest.mark.asyncio
async def test_list_facts_most_recent_first(tracker):
    """Facts are listed most-recent-first."""
    f1 = await tracker.record("old", "proj", "a1")
    f2 = await tracker.record("new", "proj", "a1")

    facts = await tracker.list_facts(project="proj")
    assert facts[0].id == f2.id
    assert facts[1].id == f1.id


@pytest.mark.asyncio
async def test_timeline_returns_chronological(tracker):
    """Timeline returns facts in chronological order."""
    f1 = await tracker.record("first", "proj", "a1")
    f2 = await tracker.record("second", "proj", "a1")
    await tracker.expire(f1.id)

    timeline = await tracker.timeline(project="proj")
    assert len(timeline) == 2
    assert timeline[0].id == f1.id  # first created
    assert timeline[1].id == f2.id


@pytest.mark.asyncio
async def test_facts_at_boundaries_are_inclusive():
    """Characterization: facts_at includes both valid_from and valid_to boundaries (inclusive)."""
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
    """Characterization: facts_at includes the expiry instant (valid_to boundary is inclusive)."""
    t = TemporalTracker()
    f = await t.record("x", "p", "a1", valid_from="2026-01-01T00:00:00")
    await t.expire(f.id, reason="changed")   # sets valid_to = now (future vs valid_from)
    vt = (await t.get_fact(f.id)).valid_to
    # at exactly valid_to → still included (inclusive end)
    assert f.id in {x.id for x in await t.facts_at("p", vt)}
    # strictly after valid_to → excluded
    assert f.id not in {x.id for x in await t.facts_at("p", "2099-01-01T00:00:00")}
