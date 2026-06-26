"""Tests for StateSnapshot / SnapshotManager."""
import pytest
from daemon.snapshots import SnapshotManager


@pytest.fixture
def mgr():
    return SnapshotManager(max_snapshots=10)


@pytest.mark.asyncio
async def test_capture_creates_snapshot(mgr):
    """Capturing returns a snapshot with the correct fields."""
    snap = await mgr.capture(
        project="proj", agent_id="a1", step=1,
        activity="reading auth.py", context_summary="loaded graph",
    )
    assert snap.id
    assert snap.project == "proj"
    assert snap.agent_id == "a1"
    assert snap.step == 1
    assert snap.activity == "reading auth.py"


@pytest.mark.asyncio
async def test_replay_returns_chronological(mgr):
    """Replay returns snapshots in chronological order."""
    await mgr.capture("proj", "a1", 1, "start")
    await mgr.capture("proj", "a1", 2, "middle")
    await mgr.capture("proj", "a1", 3, "end")

    history = await mgr.replay(project="proj", agent_id="a1")
    assert len(history) == 3
    assert history[0].step == 1
    assert history[2].step == 3


@pytest.mark.asyncio
async def test_replay_filters_by_agent(mgr):
    """Replay can filter to a specific agent."""
    await mgr.capture("proj", "agent-a", 1, "a")
    await mgr.capture("proj", "agent-b", 1, "b")

    history_a = await mgr.replay(project="proj", agent_id="agent-a")
    assert len(history_a) == 1
    assert history_a[0].agent_id == "agent-a"


@pytest.mark.asyncio
async def test_replay_all_agents(mgr):
    """Replay without agent_id returns all snapshots for the project."""
    await mgr.capture("proj", "agent-a", 1, "a")
    await mgr.capture("proj", "agent-b", 1, "b")

    history = await mgr.replay(project="proj")
    assert len(history) == 2


@pytest.mark.asyncio
async def test_replay_respects_limit(mgr):
    """Replay caps at the limit parameter."""
    for i in range(20):
        await mgr.capture("proj", "a1", i, f"step-{i}")

    history = await mgr.replay(project="proj", agent_id="a1", limit=5)
    assert len(history) == 5
