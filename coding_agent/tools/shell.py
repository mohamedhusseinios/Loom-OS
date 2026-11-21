"""Allowlisted shell commands. Anything else needs approval and is not run."""

from __future__ import annotations

from coding_agent.ports import Sandbox

SHELL_ALLOWLIST = frozenset({"pytest", "python", "python3", "npm", "npx", "ruff", "mypy", "git"})

_GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})


def shell(sandbox: Sandbox, argv: list[str]) -> dict:
    if not argv or argv[0] not in SHELL_ALLOWLIST:
        return {"ok": False, "need_approval": True, "reason": "not_allowlisted"}
    blocked = _blocked_git(argv)
    if blocked is not None:
        return blocked
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


def _blocked_git(argv: list[str]) -> dict | None:
    if not argv or argv[0] != "git":
        return None
    alias_kind, subcommand, rest = _split_git_command(argv)
    if _is_git_push(subcommand, rest) or any(token == "send-pack" for token in argv):
        if not _config_mentions_alias(subcommand, rest):
            return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    if alias_kind == "push":
        return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    if alias_kind == "bang" or _config_mentions_alias(subcommand, rest):
        return {"ok": False, "need_approval": True, "reason": "not_allowlisted"}
    return None


def _is_git_push(subcommand: str | None, rest: list[str]) -> bool:
    if subcommand == "push" or subcommand == "send-pack":
        return True
    return subcommand == "subtree" and "push" in rest


def _config_mentions_alias(subcommand: str | None, rest: list[str]) -> bool:
    return subcommand == "config" and any("alias." in token.lower() for token in rest)


def _split_git_command(argv: list[str]) -> tuple[str, str | None, list[str]]:
    alias_kind = ""
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            return alias_kind, None, []
        if arg in ("-c", "--config-env"):
            value = argv[index + 1] if index + 1 < len(argv) else ""
            alias_kind = _prefer_alias(alias_kind, _alias_option_kind(value))
            index += 2
            continue
        if arg.startswith("--config-env="):
            alias_kind = _prefer_alias(alias_kind, _alias_option_kind(arg.split("=", 1)[1]))
            index += 1
            continue
        if arg in _GIT_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if arg.startswith("--") and "=" in arg:
            index += 1
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return alias_kind, arg, argv[index + 1 :]
    return alias_kind, None, []


def _alias_option_kind(token: str) -> str:
    key, _, value = token.partition("=")
    if not key.strip().lower().startswith("alias."):
        return ""
    if value.startswith("!"):
        return "bang"
    return "push"


def _prefer_alias(current: str, new: str) -> str:
    if not new:
        return current
    if current == "push" or new == "push":
        return "push"
    return new
