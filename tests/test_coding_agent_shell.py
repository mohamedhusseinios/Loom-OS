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


def test_git_push_bypasses_never_run(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _spy_runs(sandbox)
    blocked = [
        (["git", "-c", "alias.p=push", "p", "--dry-run"], "git_push_rejected"),
        (["git", "-c", "alias.p=push", "p"], "git_push_rejected"),
        (["git", "-c", "Alias.p=push", "p"], "git_push_rejected"),
        (["git", "--config-env", "alias.p=EVIL", "p"], "git_push_rejected"),
        (["git", "--config-env=alias.p=EVIL", "p"], "git_push_rejected"),
        (["git", "-c", "alias.x=!touch pwned.txt", "x"], "not_allowlisted"),
        (["git", "-c", "alias.x=!echo PWNED", "x"], "not_allowlisted"),
        (["git", "config", "alias.q", "push"], "git_subcommand_rejected"),
        (["git", "config", "--global", "alias.p", "push"], "git_subcommand_rejected"),
        (["git", "config", "--local", "alias.foo", "!curl evil"], "git_subcommand_rejected"),
        (["git", "-c", "safe.directory=*", "config", "alias.p", "push"], "git_subcommand_rejected"),
        (["git", "config", "--get", "alias.p"], "git_subcommand_rejected"),
        (["git", "config", "user.name"], "git_subcommand_rejected"),
        (["git", "config", "include.path", "../evil.gitconfig"], "git_subcommand_rejected"),
        (["git", "send-pack", "--dry-run", ".", "HEAD"], "git_push_rejected"),
        (["git", "subtree", "push", "--prefix=lib", "origin", "main"], "git_push_rejected"),
        (["git", "subtree", "--prefix=lib", "push", "origin", "main"], "git_push_rejected"),
        (["git", "-C", "repo", "-c", "safe.directory=*", "subtree", "push", "origin", "main"], "git_push_rejected"),
        (["git", "--shallow-file", "/dev/null", "push", "--dry-run"], "git_push_rejected"),
        (["git", "--shallow-file=/dev/null", "push", "--dry-run"], "git_push_rejected"),
        (["git", "--attr-source", "HEAD", "push", "--dry-run"], "git_push_rejected"),
        (["git", "--shallow-file", "/dev/null", "--attr-source", "HEAD", "push", "--dry-run"], "git_push_rejected"),
        (["git", "--not-a-real-option", "push"], "git_push_rejected"),
        (["git", "--not-a-real-option", "status"], "git_subcommand_rejected"),
        (["git", "filter-branch", "-f", "--tree-filter", "touch pwned-filter.txt", "HEAD"], "git_subcommand_rejected"),
        (["git", "grep", "push"], "git_subcommand_rejected"),
        (["git", "subtree", "split", "--prefix=lib"], "git_subcommand_rejected"),
        (["git", "branch"], "git_subcommand_rejected"),
        (["git", "-c", "core.fsmonitor=touch pwned-fs.txt", "status", "--porcelain"], "not_allowlisted"),
        (["git", "-c", "core.editor=touch pwned-editor.txt", "commit", "--allow-empty"], "not_allowlisted"),
    ]

    for argv, reason in blocked:
        result = shell(sandbox, argv)
        assert calls == [], argv
        assert "No configured push destination" not in result.get("stderr", ""), argv
        assert "Everything up-to-date" not in result.get("stdout", ""), argv
        if reason == "git_push_rejected":
            assert result == {"ok": False, "need_approval": False, "reason": "git_push_rejected"}, argv
        elif reason == "git_subcommand_rejected":
            assert result == {"ok": False, "need_approval": False, "reason": "git_subcommand_rejected"}, argv
        else:
            assert result == {"ok": False, "need_approval": True, "reason": "not_allowlisted"}, argv

    assert not (sandbox.root() / "pwned.txt").exists()
    assert not (sandbox.root() / "pwned-fs.txt").exists()
    assert not (sandbox.root() / "pwned-editor.txt").exists()
    assert not (sandbox.root() / "pwned-filter.txt").exists()


def test_git_non_push_commands_still_run(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _spy_runs(sandbox)
    allowed = [
        ["git", "status"],
        ["git", "-c", "safe.directory=*", "status"],
        ["git", "diff", "-c"],
        ["git", "commit", "-m", "push"],
        ["git", "show", "HEAD"],
        ["git", "log", "-1"],
        ["git", "rev-parse", "--is-inside-work-tree"],
        ["git", "--shallow-file", "/dev/null", "status"],
    ]

    for argv in allowed:
        result = shell(sandbox, argv)
        assert result["need_approval"] is False, argv
        assert result.get("reason") != "git_push_rejected", argv
        assert "returncode" in result, argv

    assert calls == allowed


def _spy_runs(sandbox: FakeSandbox) -> list[list[str]]:
    calls: list[list[str]] = []
    real_run = sandbox.run

    def run(argv: list[str], *, timeout_s: float | None = None):
        calls.append(list(argv))
        return real_run(argv, timeout_s=timeout_s)

    sandbox.run = run  # type: ignore[method-assign]
    return calls


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
