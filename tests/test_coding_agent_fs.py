"""Tests for sandbox read_file and search tools."""

from __future__ import annotations

from pathlib import Path

from coding_agent.events import JsonlEventSink
from coding_agent.session import RunSession
from coding_agent.testing.fakes import FakeSandbox, FakeUsageMeter
from coding_agent.tools.fs import read_file, search


class _Llm:
    def chat(self, messages: list[dict], *, model: str) -> None:
        raise AssertionError("llm should not be called")


class _Context:
    def pack(self) -> str:
        return ""


def _session(tmp_path: Path) -> RunSession:
    root = tmp_path / "sandbox"
    root.mkdir(exist_ok=True)
    return RunSession(
        {},
        FakeSandbox(root),
        JsonlEventSink(tmp_path / "events.jsonl"),
        _Llm(),
        FakeUsageMeter(),
        _Context(),
    )


def test_read_file_returns_content(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sandbox = FakeSandbox(root)
    sandbox.write_text("a.py", "print(1)\n")

    assert read_file(sandbox, "a.py") == {"ok": True, "content": "print(1)\n"}


def test_read_file_missing(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()

    assert read_file(FakeSandbox(root), "missing.py") == {"ok": False, "reason": "not_found"}


def test_read_file_escape_denied(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = read_file(FakeSandbox(root), "../outside.txt")

    assert result == {"ok": False, "reason": "path_escape"}
    assert "secret" not in str(result)


def test_search_finds_literal_line(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sandbox = FakeSandbox(root)
    sandbox.write_text("src/a.py", "keep\nneedle here\n")
    sandbox.write_text("src/b.py", "ab\na.c\n")

    found = search(sandbox, "needle")
    literal = search(sandbox, "a.c")

    assert found == {
        "ok": True,
        "truncated": False,
        "matches": [{"path": "src/a.py", "line": 2, "text": "needle here"}],
    }
    assert literal["matches"] == [{"path": "src/b.py", "line": 2, "text": "a.c"}]


def test_search_returns_capped_lines(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sandbox = FakeSandbox(root)
    sandbox.write_text("notes.txt", "".join(f"hit {i}\n" for i in range(60)))

    result = search(sandbox, "hit")

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["matches"]) == 50
    assert result["matches"][0] == {"path": "notes.txt", "line": 1, "text": "hit 0"}
    assert result["matches"][49] == {"path": "notes.txt", "line": 50, "text": "hit 49"}


def test_search_skips_undecodable_files(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "bin.dat").write_bytes(b"\xff\xfe needle")
    sandbox = FakeSandbox(root)
    sandbox.write_text("a.txt", "needle\n")

    result = search(sandbox, "needle")

    assert result["ok"] is True
    assert result["matches"] == [{"path": "a.txt", "line": 1, "text": "needle"}]


def test_search_escape_denied(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret needle", encoding="utf-8")

    result = search(FakeSandbox(root), "needle", "..")

    assert result == {"ok": False, "reason": "path_escape"}


def test_session_read_file_and_search(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.sandbox.write_text("a.py", "needle\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    read = session.dispatch_tool("read_file", {"path": "a.py"})
    found = session.dispatch_tool("search", {"query": "needle"})
    escaped = session.dispatch_tool("read_file", {"path": "../outside.txt"})
    escaped_search = session.dispatch_tool("search", {"query": "secret", "path": ".."})

    assert read == {"ok": True, "content": "needle\n"}
    assert found["ok"] is True
    assert found["matches"] == [{"path": "a.py", "line": 1, "text": "needle"}]
    assert escaped == {"ok": False, "reason": "path_escape"}
    assert escaped_search == {"ok": False, "reason": "path_escape"}
    assert outside.read_text(encoding="utf-8") == "secret"
