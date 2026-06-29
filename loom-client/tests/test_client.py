import json
import pytest
from pathlib import Path
from loom_client import LoomClient


def test_register_writes_valid_json(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.register(
        project="my-proj",
        agent="claude-code",
        project_path=str(tmp_path),
        capabilities=["code-analysis", "review"],
    )
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["agent"] == "claude-code"
    assert data["project"] == "my-proj"
    assert data["capabilities"] == ["code-analysis", "review"]
    assert path.name == "register.json"
    assert "my-proj" in str(path)


def test_heartbeat_writes_valid_json(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.heartbeat(project="my-proj", agent="claude-code", status="working")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["agent"] == "claude-code"
    assert data["project"] == "my-proj"
    assert data["status"] == "working"
    assert "timestamp" in data


def test_finding_writes_markdown_with_frontmatter(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.finding(
        project="my-proj",
        agent="claude-code",
        title="Auth Service Review",
        body="The AuthService class handles login via BcryptHasher.",
        files=["src/auth.py"],
        type="code-analysis",
    )
    assert path.exists()
    assert path.name.startswith("finding-")
    assert path.suffix == ".md"
    content = path.read_text()
    assert content.startswith("---")
    assert "agent: claude-code" in content
    assert "project: my-proj" in content
    assert "type: code-analysis" in content
    assert "src/auth.py" in content
    parts = content.split("---", 2)
    assert len(parts) >= 3
    assert "AuthService" in parts[2]


def test_task_writes_valid_json(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.task(
        project="my-proj",
        title="Fix auth bug",
        instruction="Fix the XSS vulnerability in the login form",
        target_agent="codex",
        priority="high",
    )
    assert path.exists()
    assert path.name.startswith("task-")
    assert path.suffix == ".json"
    data = json.loads(path.read_text())
    assert data["target_agent"] == "codex"
    assert data["instruction"] == "Fix the XSS vulnerability in the login form"
    assert data["priority"] == "high"
    assert "task_id" in data


def test_finding_filename_is_slugified(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.finding(
        project="p", agent="a", title="Auth Service Review!",
        body="body",
    )
    assert " " not in path.name
    assert "!" not in path.name