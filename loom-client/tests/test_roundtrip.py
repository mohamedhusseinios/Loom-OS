"""Round-trip test: SDK writes a file, daemon models parse it successfully.

This catches schema drift between the SDK and the daemon.
"""
import json
import sys
from pathlib import Path

# Add the daemon package to the path for this test
daemon_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(daemon_root))

from loom_client import LoomClient
from daemon.models import RegisterPayload, HeartbeatPayload, TaskPayload


def test_register_file_parses_with_daemon_models(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.register(
        project="roundtrip",
        agent="claude-code",
        project_path=str(tmp_path),
        capabilities=["code-analysis"],
        version="1.5",
    )
    data = json.loads(path.read_text())
    payload = RegisterPayload(**data)
    assert payload.agent == "claude-code"
    assert payload.version == "1.5"
    assert payload.capabilities == ["code-analysis"]


def test_heartbeat_file_parses_with_daemon_models(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.heartbeat(project="rt", agent="codex", status="working")
    data = json.loads(path.read_text())
    payload = HeartbeatPayload(**data)
    assert payload.agent == "codex"
    assert payload.status == "working"


def test_task_file_parses_with_daemon_models(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.task(
        project="rt",
        title="Test task",
        instruction="Write tests",
        target_agent="codex",
        priority="high",
    )
    data = json.loads(path.read_text())
    payload = TaskPayload(**data)
    assert payload.target_agent == "codex"
    assert payload.priority == "high"