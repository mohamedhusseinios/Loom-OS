"""Sandbox read and literal line search.

`search` walks files under the sandbox root and filters lines in Python.
It does not require an `rg` binary, so FakeSandbox tests stay hermetic.
The walk skips `.git`, `__pycache__`, and `.venv` directories.
Results are capped at MAX_SEARCH_MATCHES lines.
"""

from __future__ import annotations

import os
from pathlib import Path

from coding_agent.ports import Sandbox

MAX_SEARCH_MATCHES = 50
_SKIP_WALK_DIRS = frozenset({".git", "__pycache__", ".venv"})


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
        files = _walk_files(base)
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


def _walk_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_WALK_DIRS]
        for name in filenames:
            files.append(Path(dirpath) / name)
    files.sort()
    return files


def _contained(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError(rel)
    return target
