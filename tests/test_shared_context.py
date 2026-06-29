"""Tests for shared context agent roster with user column."""
import pytest
from daemon.shared_context import _agent_roster


@pytest.mark.asyncio
async def test_agent_roster_shows_user():
    class _Reg:
        async def list_agents(self, project=None, user=None):
            from daemon.models import AgentInfo, AgentStatus
            return [
                AgentInfo(agent_id="a-p-alice", agent_name="claude", version="1.0",
                         project="p", capabilities=["review"], user="alice"),
                AgentInfo(agent_id="a-p-bob", agent_name="codex", version="1.0",
                         project="p", capabilities=["test"], user="bob"),
            ]
    roster = await _agent_roster("p", _Reg())
    assert "alice" in roster
    assert "bob" in roster
    assert "User" in roster  # column header
