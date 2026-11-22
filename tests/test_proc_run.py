"""Tests for coding_agent.proc_run."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from coding_agent.proc_run import TrackedProcess, scrub_tool_env


def test_scrub_tool_env_drops_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    cleaned = scrub_tool_env()
    assert "DEEPSEEK_API_KEY" not in cleaned
    assert "LOOM_AGENT_API_KEY" not in cleaned
    assert "PATH" in cleaned


def test_tracked_process_env_scrub_visible_to_child(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-leak-test")
    tracked = TrackedProcess()
    script = "import os; print(os.environ.get('DEEPSEEK_API_KEY', 'MISSING'))"
    proc = tracked.run([sys.executable, "-c", script], tmp_path, timeout_s=30)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "MISSING"