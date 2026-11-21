"""Tests for shell allowlist, git tools (no push), and manifest test/lint."""

from __future__ import annotations

import os
from pathlib import Path

from coding_agent.events import JsonlEventSink
from coding_agent.session import RunSession
from coding_agent.testing.fakes import FakeSandbox, FakeUsageMeter
from coding_agent.tools.git_tools import git_add, git_commit, git_diff, git_log, git_status
from coding_agent.tools.shell import SHELL_ALLOWLIST, shell
from coding_agent.tools.test_lint import run_lint, run_tests


class _Llm:
    def chat(self, messages: list[dict], *, model: str) -> None:
        raise AssertionError("llm should not be called")


class _Context:
    def pack(self) -> str:
        return ""


def _session(tmp_path: Path, **manifest: object) -> RunSession:
    root = tmp_path / "sandbox"
    root.mkdir(exist_ok=True)
    return RunSession(
        manifest,
        FakeSandbox(root),
        JsonlEventSink(tmp_path / "events.jsonl"),
        _Llm(),
        FakeUsageMeter(),
        _Context(),
    )


def _sandbox(tmp_path: Path) -> FakeSandbox:
    root = tmp_path / "sandbox"
    root.mkdir()
    return FakeSandbox(root)


def test_allowlist_v1_members() -> None:
    assert SHELL_ALLOWLIST == frozenset({"pytest", "python", "python3", "npm", "npx", "ruff", "mypy", "git"})


def test_allowlisted_pytest_runs(tmp_path: Path, monkeypatch) -> None:
    venv_bin = Path(__file__).resolve().parents[1] / ".venv" / "bin"
    monkeypatch.setenv("PATH", str(venv_bin) + os.pathsep + os.environ.get("PATH", ""))
    sandbox = _sandbox(tmp_path)

    result = shell(sandbox, ["pytest", "--version"])

    assert result["need_approval"] is False
    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "pytest" in result["stdout"]


def test_rm_needs_approval_and_does_not_run(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    sandbox.write_text("victim.txt", "keep")

    result = shell(sandbox, ["rm", "victim.txt"])

    assert result == {"ok": False, "need_approval": True, "reason": "not_allowlisted"}
    assert sandbox.read_text("victim.txt") == "keep"


def test_git_push_rejected_without_running(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)

    direct = shell(sandbox, ["git", "push"])
    with_remote = shell(sandbox, ["git", "push", "origin", "main"])
    flagged = shell(sandbox, ["git", "-c", "safe.directory=*", "push", "--dry-run"])

    assert direct == {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    assert with_remote["reason"] == "git_push_rejected"
    assert flagged["reason"] == "git_push_rejected"
    assert "not a git repository" not in direct.get("stderr", "")


def test_other_git_commands_still_run(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)

    result = shell(sandbox, ["git", "status"])

    assert result["need_approval"] is False
    assert result.get("reason") != "git_push_rejected"
    assert result["returncode"] != 0
    assert "not a git repository" in result["stderr"]


def test_git_status_diff_log_add_commit(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    assert sandbox.run(["git", "init"]).returncode == 0
    sandbox.write_text("a.txt", "hello\n")

    added = git_add(sandbox, ["a.txt"])
    committed = git_commit(sandbox, "add a")
    status = git_status(sandbox)
    log = git_log(sandbox)
    sandbox.write_text("a.txt", "hello\nworld\n")
    diff = git_diff(sandbox)

    assert added["ok"] is True
    assert committed["ok"] is True
    assert status["ok"] is True
    assert status["stdout"].strip() == ""
    assert "add a" in log["stdout"]
    assert "world" in diff["stdout"]


def test_git_tool_push_rejected(tmp_path: Path) -> None:
    session = _session(tmp_path)

    result = session.dispatch_tool("git", {"subcommand": "push"})

    assert result == {"ok": False, "need_approval": False, "reason": "git_push_rejected"}


def test_run_tests_and_run_lint_use_manifest_commands(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    manifest = {
        "test_command": ["python3", "-c", "open('ran-tests','w').write('yes')"],
        "lint_command": ["python3", "-c", "open('ran-lint','w').write('yes')"],
    }
    sandbox = FakeSandbox(root)

    tests = run_tests(sandbox, manifest)
    lint = run_lint(sandbox, manifest)

    assert tests["ok"] is True
    assert tests["returncode"] == 0
    assert lint["ok"] is True
    assert (root / "ran-tests").read_text(encoding="utf-8") == "yes"
    assert (root / "ran-lint").read_text(encoding="utf-8") == "yes"


def test_dispatch_tool_wires_shell_git_and_test_lint(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    sandbox = FakeSandbox(root)
    assert sandbox.run(["git", "init"]).returncode == 0
    sandbox.write_text("a.txt", "hello\n")
    session = RunSession(
        {
            "test_command": ["python3", "-c", "open('ran-tests','w').write('yes')"],
            "lint_command": ["python3", "-c", "open('ran-lint','w').write('yes')"],
        },
        sandbox,
        JsonlEventSink(tmp_path / "events.jsonl"),
        _Llm(),
        FakeUsageMeter(),
        _Context(),
    )

    blocked = session.dispatch_tool("shell", {"argv": ["rm", "a.txt"]})
    pushed = session.dispatch_tool("shell", {"argv": ["git", "push"]})
    added = session.dispatch_tool("git", {"subcommand": "add", "paths": ["a.txt"]})
    committed = session.dispatch_tool("git", {"subcommand": "commit", "message": "via dispatch"})
    status = session.dispatch_tool("git", {"subcommand": "status"})
    tests = session.dispatch_tool("run_tests", {})
    lint = session.dispatch_tool("run_lint", {})

    assert blocked["need_approval"] is True
    assert sandbox.read_text("a.txt") == "hello\n"
    assert pushed["reason"] == "git_push_rejected"
    assert added["ok"] is True
    assert committed["ok"] is True
    assert status["ok"] is True
    assert "via dispatch" in session.dispatch_tool("git", {"subcommand": "log"})["stdout"]
    assert tests["ok"] is True
    assert lint["ok"] is True
    assert (root / "ran-tests").read_text(encoding="utf-8") == "yes"
    assert (root / "ran-lint").read_text(encoding="utf-8") == "yes"
