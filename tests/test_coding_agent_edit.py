"""Tests for SEARCH/REPLACE edit."""

from __future__ import annotations

from pathlib import Path

from coding_agent.events import JsonlEventSink
from coding_agent.session import RunSession
from coding_agent.testing.fakes import FakeSandbox, FakeUsageMeter
from coding_agent.tools.edit import ApplyResult, apply_search_replace, edit


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


def test_exact_apply(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")

    result = apply_search_replace(path, "return 1", "return 2")

    assert result == ApplyResult(ok=True, reason=None)
    assert path.read_text(encoding="utf-8") == "def f():\n    return 2\n"


def test_exact_match_wins_over_nearby_fuzzy(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello world\nhello worlb\n", encoding="utf-8")

    result = apply_search_replace(path, "hello world\n", "OK\n")

    assert result == ApplyResult(ok=True, reason=None)
    assert path.read_text(encoding="utf-8") == "OK\nhello worlb\n"


def test_not_found_leaves_file_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("alpha\n", encoding="utf-8")

    result = apply_search_replace(path, "zzzzzzzzzz", "nope")

    assert result == ApplyResult(ok=False, reason="not_found")
    assert path.read_text(encoding="utf-8") == "alpha\n"


def test_missing_file_is_not_found(tmp_path: Path) -> None:
    result = apply_search_replace(tmp_path / "missing.txt", "a", "b")

    assert result == ApplyResult(ok=False, reason="not_found")


def test_empty_search_is_not_found(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello\n", encoding="utf-8")

    result = apply_search_replace(path, "", "x")

    assert result == ApplyResult(ok=False, reason="not_found")
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_multiple_matches_leaves_file_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("foo\nfoo\n", encoding="utf-8")

    result = apply_search_replace(path, "foo", "bar")

    assert result == ApplyResult(ok=False, reason="multiple_matches")
    assert path.read_text(encoding="utf-8") == "foo\nfoo\n"


def test_fuzzy_unique_apply(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("alpha\nhello world\nomega\n", encoding="utf-8")

    result = apply_search_replace(path, "hello worlb\n", "hello there\n")

    assert result == ApplyResult(ok=True, reason=None)
    assert path.read_text(encoding="utf-8") == "alpha\nhello there\nomega\n"


def test_fuzzy_unique_multiline_apply(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("line one\nline two\nline three\n", encoding="utf-8")

    result = apply_search_replace(path, "line one\nline twp\n", "LINE ONE\nLINE TWO\n")

    assert result == ApplyResult(ok=True, reason=None)
    assert path.read_text(encoding="utf-8") == "LINE ONE\nLINE TWO\nline three\n"


def test_ambiguous_fuzzy_leaves_file_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    original = "hello world\nhello worlb\n"
    path.write_text(original, encoding="utf-8")

    result = apply_search_replace(path, "hello worlc\n", "nope\n")

    assert result == ApplyResult(ok=False, reason="ambiguous_fuzzy")
    assert path.read_text(encoding="utf-8") == original


def test_fuzzy_below_bound_is_not_found(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    original = "hello world\n"
    path.write_text(original, encoding="utf-8")

    result = apply_search_replace(path, "hello wXrXd\n", "nope\n")

    assert result == ApplyResult(ok=False, reason="not_found")
    assert path.read_text(encoding="utf-8") == original


def test_edit_escape_denied(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    sandbox = FakeSandbox(root)

    result = edit(sandbox, "../outside.txt", "secret", "pwned")

    assert result == {"ok": False, "reason": "path_escape"}
    assert outside.read_text(encoding="utf-8") == "secret"


def test_session_edit_exact_and_escape(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.sandbox.write_text("a.py", "value = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    applied = session.dispatch_tool(
        "edit",
        {"path": "a.py", "search": "value = 1\n", "replace": "value = 2\n"},
    )
    escaped = session.dispatch_tool(
        "edit",
        {"path": "../outside.txt", "search": "secret", "replace": "pwned"},
    )

    assert applied == {"ok": True, "reason": None}
    assert session.sandbox.read_text("a.py") == "value = 2\n"
    assert escaped == {"ok": False, "reason": "path_escape"}
    assert outside.read_text(encoding="utf-8") == "secret"
