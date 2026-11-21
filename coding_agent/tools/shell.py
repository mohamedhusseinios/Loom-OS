"""Allowlisted shell commands. Git runs only an allowlisted subcommand."""

from __future__ import annotations

from coding_agent.ports import Sandbox

SHELL_ALLOWLIST = frozenset({"pytest", "python", "python3", "npm", "npx", "ruff", "mypy", "git"})

_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "add", "commit", "rev-parse"})

_GIT_VALUE_OPTIONS = frozenset({
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
    "--shallow-file",
    "--attr-source",
})

_GIT_FLAG_OPTIONS = frozenset({
    "-h",
    "-p",
    "-P",
    "-v",
    "--help",
    "--version",
    "--paginate",
    "--no-pager",
    "--bare",
    "--no-replace-objects",
    "--no-lazy-fetch",
    "--no-optional-locks",
    "--no-advice",
    "--html-path",
    "--man-path",
    "--info-path",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--exec-path",
})

_SAFE_CONFIG_KEY = "safe.directory"


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
    if any(token == "send-pack" for token in argv):
        return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    parsed = _parse_git_invocation(argv)
    if parsed is None:
        if any(token == "push" for token in argv):
            return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
        return {"ok": False, "need_approval": False, "reason": "git_subcommand_rejected"}
    alias_kind, subcommand, rest, bad_config = parsed
    if subcommand in ("push", "send-pack") or (subcommand == "subtree" and "push" in rest):
        return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    if alias_kind == "push":
        return {"ok": False, "need_approval": False, "reason": "git_push_rejected"}
    if alias_kind == "bang" or bad_config:
        return {"ok": False, "need_approval": True, "reason": "not_allowlisted"}
    if subcommand not in _GIT_SUBCOMMANDS:
        return {"ok": False, "need_approval": False, "reason": "git_subcommand_rejected"}
    return None


def _parse_git_invocation(argv: list[str]) -> tuple[str, str | None, list[str], bool] | None:
    alias_kind = ""
    bad_config = False
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            index += 1
            break
        name, attached = _split_option(arg)
        if name in ("-c", "--config-env"):
            if attached is None:
                if index + 1 >= len(argv):
                    return None
                token = argv[index + 1]
                index += 2
            else:
                token = attached
                index += 1
            alias_kind, bad_config = _note_config(token, alias_kind, bad_config)
            continue
        if name in _GIT_VALUE_OPTIONS:
            if attached is None:
                if index + 1 >= len(argv):
                    return None
                index += 2
            else:
                index += 1
            continue
        if name in _GIT_FLAG_OPTIONS:
            index += 1
            continue
        if attached is not None:
            index += 1
            continue
        if arg.startswith("-"):
            return None
        return alias_kind, arg, argv[index + 1 :], bad_config
    if index >= len(argv):
        return alias_kind, None, [], bad_config
    if argv[index].startswith("-"):
        return None
    return alias_kind, argv[index], argv[index + 1 :], bad_config


def _split_option(arg: str) -> tuple[str, str | None]:
    if arg.startswith("--") and "=" in arg:
        name, value = arg.split("=", 1)
        return name, value
    return arg, None


def _note_config(token: str, alias_kind: str, bad_config: bool) -> tuple[str, bool]:
    kind = _alias_option_kind(token)
    if kind:
        return _prefer_alias(alias_kind, kind), bad_config
    key, _, _value = token.partition("=")
    if key.strip().lower() != _SAFE_CONFIG_KEY:
        bad_config = True
    return alias_kind, bad_config


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
