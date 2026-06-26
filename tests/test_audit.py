"""Tests for the AuditTrail."""
import pytest
from daemon.audit import AuditTrail


@pytest.fixture
async def audit(tmp_path):
    a = AuditTrail(db_path=str(tmp_path / "test.db"))
    await a.initialize()
    yield a
    await a.close()


@pytest.mark.asyncio
async def test_record_creates_event(audit):
    """Recording an event stores it and returns an id."""
    event_id = await audit.record(
        project="proj", agent_id="agent-1",
        action="finding:ingested", details={"file": "f.md"},
    )
    assert event_id

    events = await audit.query(project="proj")
    assert len(events) == 1
    assert events[0]["action"] == "finding:ingested"
    assert events[0]["details"]["file"] == "f.md"


@pytest.mark.asyncio
async def test_query_filters_by_agent(audit):
    """Events can be filtered by agent_id."""
    await audit.record("proj", "agent-a", "register", {})
    await audit.record("proj", "agent-b", "register", {})

    events = await audit.query(agent_id="agent-a")
    assert len(events) == 1
    assert events[0]["agent_id"] == "agent-a"


@pytest.mark.asyncio
async def test_query_filters_by_action(audit):
    """Events can be filtered by action type."""
    await audit.record("proj", "a1", "register", {})
    await audit.record("proj", "a1", "heartbeat", {})

    events = await audit.query(action="heartbeat")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_query_most_recent_first(audit):
    """Events are returned in most-recent-first order."""
    await audit.record("proj", "a1", "first", {})
    await audit.record("proj", "a1", "second", {})

    events = await audit.query(project="proj")
    assert events[0]["action"] == "second"
    assert events[1]["action"] == "first"


@pytest.mark.asyncio
async def test_query_with_no_filters(audit):
    """Query with no filters returns all events."""
    await audit.record("proj-a", "a1", "x", {})
    await audit.record("proj-b", "a2", "y", {})

    events = await audit.query()
    assert len(events) == 2


@pytest.mark.asyncio
async def test_summary_returns_daily_counts(audit):
    """Summary aggregates action counts per day."""
    await audit.record("proj", "a1", "finding:ingested", {})
    await audit.record("proj", "a1", "finding:ingested", {})
    await audit.record("proj", "a2", "agent:dispatched", {})

    summary = await audit.summary(project="proj")
    assert len(summary) > 0
    today = summary[0]
    # Should have 2 finding:ingested and 1 agent:dispatched today
    all_counts = sum(today["actions"].values())
    assert all_counts == 3
