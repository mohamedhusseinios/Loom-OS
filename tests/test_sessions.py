"""Tests for the SessionManager."""
import pytest
from daemon.sessions import SessionManager, Session


@pytest.fixture
def manager(tmp_path):
    return SessionManager(base_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_start_session_creates_unique_id(manager):
    """Starting a session returns a valid Session with a unique id."""
    session = await manager.start_session(agent_id="agent-1", project="test-proj")
    assert session is not None
    assert session.id
    assert session.agent_id == "agent-1"
    assert session.project == "test-proj"
    assert session.active is True


@pytest.mark.asyncio
async def test_sessions_are_isolated(manager):
    """Different agents get different sessions."""
    s1 = await manager.start_session(agent_id="agent-a", project="proj")
    s2 = await manager.start_session(agent_id="agent-b", project="proj")
    assert s1.id != s2.id
    assert s1.agent_id != s2.agent_id


@pytest.mark.asyncio
async def test_end_session_marks_inactive(manager):
    """Ending a session marks it as inactive."""
    session = await manager.start_session(agent_id="agent-1", project="test-proj")
    await manager.end_session(session.id)
    assert session.active is False


@pytest.mark.asyncio
async def test_add_and_get_context(manager):
    """Context items can be added to and retrieved from a session."""
    session = await manager.start_session(agent_id="agent-1", project="test-proj")

    await manager.add_context(session.id, "file:auth.py", "Authentication module")
    await manager.add_context(session.id, "entity:User", "User class definition")

    # Active session can be retrieved
    retrieved = await manager.get_session(session.id)
    assert retrieved is not None
    assert len(retrieved.context) == 2
    assert "file:auth.py" in retrieved.context


@pytest.mark.asyncio
async def test_get_session_nonexistent_returns_none(manager):
    """Looking up a nonexistent session returns None."""
    result = await manager.get_session("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_active_sessions(manager):
    """Only active sessions are listed."""
    s1 = await manager.start_session(agent_id="agent-1", project="proj")
    s2 = await manager.start_session(agent_id="agent-2", project="proj")
    await manager.end_session(s2.id)

    active = await manager.list_active_sessions(project="proj")
    assert len(active) == 1
    assert active[0].id == s1.id


@pytest.mark.asyncio
async def test_list_active_sessions_filters_by_project(manager):
    """Active sessions are filtered to the requested project."""
    await manager.start_session(agent_id="agent-1", project="proj-a")
    await manager.start_session(agent_id="agent-2", project="proj-b")

    active_a = await manager.list_active_sessions(project="proj-a")
    assert len(active_a) == 1
    assert active_a[0].project == "proj-a"


@pytest.mark.asyncio
async def test_end_session_survives_write_failure(tmp_path, monkeypatch):
    """A mailbox write failure must NOT crash session close."""
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
    """Calling end_session twice must not re-bridge findings."""
    mgr = SessionManager(base_dir=str(tmp_path))
    s = await mgr.start_session("a1", "p")
    await mgr.add_context(s.id, "k", "v")
    await mgr.end_session(s.id)
    inbox = tmp_path / "inbox" / "p"
    after_first = sorted(inbox.glob("finding-*.md"))
    await mgr.end_session(s.id)               # second close must not re-bridge
    after_second = sorted(inbox.glob("finding-*.md"))
    assert after_first == after_second and len(after_first) == 1
