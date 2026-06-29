"""Tests for the loom CLI."""
import json
import os
from daemon.main import cmd_init
from types import SimpleNamespace


def test_init_scaffolds_inbox_and_register(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cmd_init(SimpleNamespace(project="demo", project_path=str(tmp_path),
                             agent="claude-code"))
    reg = tmp_path / ".loom" / "inbox" / "demo" / "register.json"
    assert reg.exists()
    assert json.loads(reg.read_text())["project"] == "demo"