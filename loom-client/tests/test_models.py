import pytest
from loom_client.models import RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload


def test_register_payload_defaults():
    p = RegisterPayload(agent="claude-code", project="my-proj", project_path="/tmp")
    assert p.version == "1.0"
    assert p.capabilities == []


def test_finding_payload():
    p = FindingPayload(agent="claude-code", project="my-proj", title="Auth bug", body="Found XSS")
    assert p.type == "general"
    assert p.title == "Auth bug"


def test_task_payload():
    p = TaskPayload(task_id="abc123", target_agent="codex", instruction="Review PR")
    assert p.priority == "medium"
    assert p.dispatched_by == "sdk"