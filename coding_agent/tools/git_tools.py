"""Git status, diff, log, add, and commit via the sandbox. No push."""

from __future__ import annotations

from coding_agent.ports import CompletedProc, Sandbox

_REJECTED_PUSH = {"ok": False, "need_approval": False, "reason": "git_push_rejected"}


def git_status(sandbox: Sandbox) -> dict:
    return _run(sandbox, ["git", "-c", "safe.directory=*", "status", "--porcelain"])


def git_diff(sandbox: Sandbox) -> dict:
    return _run(sandbox, ["git", "-c", "safe.directory=*", "diff"])


def git_log(sandbox: Sandbox, limit: int = 20) -> dict:
    return _run(sandbox, ["git", "-c", "safe.directory=*", "log", "-n", str(limit), "--oneline"])


def git_add(sandbox: Sandbox, paths: list[str]) -> dict:
    if not paths:
        return {"ok": False, "need_approval": False, "reason": "no_paths"}
    return _run(sandbox, ["git", "-c", "safe.directory=*", "add", "--", *paths])


def git_commit(sandbox: Sandbox, message: str) -> dict:
    if message == "":
        return {"ok": False, "need_approval": False, "reason": "empty_message"}
    return _run(sandbox, ["git", "-c", "safe.directory=*", "-c", "user.email=loom@example.com", "-c", "user.name=Loom", "-c", "commit.gpgsign=false", "commit", "-m", message])


def git_tool(sandbox: Sandbox, args: dict) -> dict:
    subcommand = args.get("subcommand", "")
    if subcommand == "push":
        return dict(_REJECTED_PUSH)
    if subcommand == "status":
        return git_status(sandbox)
    if subcommand == "diff":
        return git_diff(sandbox)
    if subcommand == "log":
        return git_log(sandbox)
    if subcommand == "add":
        return git_add(sandbox, list(args.get("paths") or []))
    if subcommand == "commit":
        return git_commit(sandbox, str(args.get("message") or ""))
    return {"ok": False, "need_approval": False, "reason": "unsupported_git_command"}


def _run(sandbox: Sandbox, argv: list[str]) -> dict:
    try:
        return _from_proc(sandbox.run(argv))
    except OSError as exc:
        return {"ok": False, "need_approval": False, "reason": "spawn_failed", "stderr": str(exc)}


def _from_proc(proc: CompletedProc) -> dict:
    return {"ok": proc.returncode == 0, "need_approval": False, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
