from daemon.worker import Worker, ClaudeResult


def _worker(**kw):
    return Worker(
        project="noor", agent="claude-code",
        project_path="/tmp/noor", base_url="http://x", **kw,
    )


def test_agent_id_matches_daemon_convention():
    assert _worker().agent_id == "claude-code-noor"


def test_eligible_filters_by_assignee_and_inflight():
    w = _worker()
    tasks = [
        {"id": "1", "assignee": "claude-code-noor"},
        {"id": "2", "assignee": "someone-else"},
        {"id": "3", "assignee": "claude-code-noor"},
    ]
    w._inflight.add("3")
    eligible = w.eligible(tasks)
    assert [t["id"] for t in eligible] == ["1"]
