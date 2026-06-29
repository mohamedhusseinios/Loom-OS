"""Tests for the LangChain-Loom memory integration."""
import pytest
from pathlib import Path
from langchain_loom.memory import LoomMemory


def test_loom_memory_load_returns_empty_when_no_context(tmp_path):
    """When no SHARED_CONTEXT.md exists, returns empty string."""
    mem = LoomMemory(project="p", project_path=str(tmp_path))
    result = mem.load_memory_variables({})
    assert "loom_context" in result
    assert result["loom_context"] == ""


def test_loom_memory_load_reads_shared_context(tmp_path):
    """Reads SHARED_CONTEXT.md when it exists."""
    loom_dir = tmp_path / ".loom"
    loom_dir.mkdir()
    (loom_dir / "SHARED_CONTEXT.md").write_text("# Shared Context\nTest data")
    mem = LoomMemory(project="p", project_path=str(tmp_path))
    result = mem.load_memory_variables({})
    assert "Test data" in result["loom_context"]


def test_loom_memory_save_writes_finding(tmp_path):
    """save_context writes a finding to the Loom inbox."""
    from loom_client import LoomClient

    client = LoomClient(loom_dir=str(tmp_path / "loom"))
    mem = LoomMemory(
        loom_client=client,
        project="p",
        agent="test-agent",
        project_path=str(tmp_path),
    )
    mem.save_context(
        inputs={"input": "What is the auth module?"},
        outputs={"output": "AuthService handles login."},
    )
    inbox = tmp_path / "loom" / "inbox" / "p"
    findings = list(inbox.glob("finding-*.md"))
    assert len(findings) == 1
    content = findings[0].read_text()
    assert "auth module" in content
    assert "AuthService" in content


def test_loom_memory_clear_is_noop():
    """clear() does nothing — findings are durable."""
    mem = LoomMemory(project="p")
    mem.clear()  # should not raise


def test_loom_memory_memory_variables():
    """memory_variables property returns ['loom_context']."""
    mem = LoomMemory(project="p")
    assert mem.memory_variables == ["loom_context"]
