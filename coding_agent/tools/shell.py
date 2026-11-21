"""Allowlisted shell commands. Anything else needs approval and is not run."""

from __future__ import annotations

from coding_agent.ports import Sandbox

SHELL_ALLOWLIST = frozenset({"pytest", "python", "python3", "npm", "npx", "ruff", "mypy", "git"})

_GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})


def shell(sandbox: Sandbox, argv: list[str]) -> dict:
    if not argv or argv[0] not in SHELL_ALLOWLIST:
        return {"ok": False, "need_approval": True, "reason": "not_allowlisted"}
    if _is_git_push(argv):
        return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    try:
        proc = sandbox.run(list(argv))
    except OSError as exc:
        return {"ok": False, "need_approval": False, "reason": "spawn_failed", "stderr": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "need_approval": False,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _is_git_push(argv: list[str]) -> bool:
    if not argv or argv[0] != "git":
        return False
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            return False
        if arg in _GIT_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg == "push"
    return False
