"""Tests for JsonlEventSink and FakeSandbox."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from coding_agent.events import JsonlEventSink
from coding_agent.testing.fakes import FakeSandbox


def test_jsonl_append_is_line_delimited_dicts(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit({"type": "run.started", "run_id": "abc"})
    sink.emit({"type": "step", "n": 1})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"type": "run.started", "run_id": "abc"}
    assert json.loads(lines[1]) == {"type": "step", "n": 1}


def test_fake_sandbox_read_write_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sb = FakeSandbox(root)
    assert sb.root() == root.resolve()

    sb.write_text("subdir/hello.txt", "world")
    assert (root / "subdir" / "hello.txt").read_text(encoding="utf-8") == "world"
    assert sb.read_text("subdir/hello.txt") == "world"


def test_fake_sandbox_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sb = FakeSandbox(root)

    with pytest.raises(ValueError):
        sb.read_text("../outside.txt")

    with pytest.raises(ValueError):
        sb.write_text("../../escape.txt", "nope")


def test_fake_sandbox_kills_child_on_cancel(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    state = {"cancel": False}
    sb = FakeSandbox(root, cancel=lambda: state["cancel"])

    def _flip() -> None:
        time.sleep(0.15)
        state["cancel"] = True

    import threading
    threading.Thread(target=_flip, daemon=True).start()
    started = time.monotonic()
    proc = sb.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=10)

    assert time.monotonic() - started < 5
    assert proc.returncode != 0
    assert "cancelled" in proc.stderr
    assert sb._tracked.child is None


def test_fake_sandbox_times_out(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sb = FakeSandbox(root)
    started = time.monotonic()
    proc = sb.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.2)

    assert time.monotonic() - started < 5
    assert proc.returncode != 0
    assert "timeout" in proc.stderr
    assert sb._tracked.child is None