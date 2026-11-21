"""Sandbox read and literal line search.

`search` walks files under the sandbox root and filters lines in Python.
It does not require an `rg` binary, so FakeSandbox tests stay hermetic.
Results are capped at MAX_SEARCH_MATCHES lines.
"""

from __future__ import annotations

from pathlib import Path

from coding_agent.ports import Sandbox

MAX_SEARCH_MATCHES = 50


def read_file(sandbox: Sandbox, path: str) -> dict:
    try:
        content = sandbox.read_text(path)
    except UnicodeDecodeError:
        return {"ok": False, "reason": "not_found"}
    except ValueError:
        return {"ok": False, "reason": "path_escape"}
    except OSError:
        return {"ok": False, "reason": "not_found"}
    return {"ok": True, "content": content}


def search(sandbox: Sandbox, query: str, path: str = ".") -> dict:
    root = sandbox.root().resolve()
    try:
        base = _contained(root, path)
    except ValueError:
        return {"ok": False, "reason": "path_escape"}
    if base.is_file():
        files = [base]
    elif base.is_dir():
        files = sorted(item for item in base.rglob("*") if item.is_file())
    else:
        return {"ok": True, "matches": [], "truncated": False}

    matches: list[dict] = []
    truncated = False
    for file in files:
        rel = file.relative_to(root).as_posix()
        try:
            text = sandbox.read_text(rel)
        except (OSError, UnicodeError, ValueError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if query not in line:
                continue
            if len(matches) >= MAX_SEARCH_MATCHES:
                truncated = True
                break
            matches.append({"path": rel, "line": line_no, "text": line})
        if truncated:
            break
    return {"ok": True, "matches": matches, "truncated": truncated}


def _contained(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError(rel)
    return target
