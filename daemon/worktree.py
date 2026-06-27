"""Git worktree helpers for isolated, autonomous task execution.

Each running task gets its own worktree + branch so an agent can edit
freely without touching the user's main checkout. Synchronous subprocess
calls — async callers should wrap these in ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True, text=True,
    )


def create_worktree(repo_path: str, workspace_path: str, branch: str, base_ref: str = "HEAD") -> None:
    """Create a new worktree at ``workspace_path`` on a fresh ``branch``."""
    Path(workspace_path).parent.mkdir(parents=True, exist_ok=True)
    proc = _run(repo_path, "worktree", "add", "-b", branch, workspace_path, base_ref)
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {proc.stderr.strip()}")


def current_branch(repo_path: str) -> str:
    proc = _run(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def commit_all(workspace_path: str, message: str) -> bool:
    """Stage and commit everything in the worktree. Returns False if clean."""
    _run(workspace_path, "add", "-A")
    status = _run(workspace_path, "status", "--porcelain")
    if not status.stdout.strip():
        return False
    proc = _run(workspace_path, "commit", "-m", message)
    if proc.returncode != 0:
        raise RuntimeError(f"git commit failed: {proc.stderr.strip()}")
    return True


def branch_diff(repo_path: str, base_branch: str, branch: str) -> str:
    """Three-dot diff: changes on ``branch`` since it diverged from base."""
    proc = _run(repo_path, "diff", f"{base_branch}...{branch}")
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {proc.stderr.strip()}")
    return proc.stdout


def merge_branch(repo_path: str, branch: str) -> tuple[bool, str]:
    """Merge ``branch`` into the repo's current branch (no fast-forward)."""
    proc = _run(repo_path, "merge", "--no-ff", "-m", f"Merge {branch}", branch)
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def list_branches(repo_path: str) -> dict:
    """Local + remote branches for choosing a merge target.

    Returns ``{"current": str, "branches": [{"name": str, "remote": bool}]}``.
    Excludes ``loom/task-*`` branches and ``*/HEAD``, and omits a remote
    branch when a local branch of the same short name already exists.
    """
    current = current_branch(repo_path)
    local_proc = _run(repo_path, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    remote_proc = _run(repo_path, "for-each-ref", "--format=%(refname:short)", "refs/remotes")
    local = [n for n in local_proc.stdout.split("\n") if n and not n.startswith("loom/task-")]
    local_set = set(local)
    branches = [{"name": n, "remote": False} for n in local]
    for n in remote_proc.stdout.split("\n"):
        if not n or n.endswith("/HEAD"):
            continue
        short = n.split("/", 1)[1] if "/" in n else n
        if short in local_set:
            continue
        branches.append({"name": n, "remote": True})
    return {"current": current, "branches": branches}


def merge_branch_into(repo_path: str, source_branch: str, target: str,
                      *, target_is_remote: bool = False) -> tuple[bool, str]:
    """Merge ``source_branch`` into ``target`` (no fast-forward).

    If ``target`` is the repo's checked-out branch, merge in place (same as
    ``merge_branch``). Otherwise the merge runs inside a throwaway worktree so
    the user's working checkout is never switched. For a remote ``target``
    (e.g. ``origin/X``) a local branch ``X`` is created from it; nothing is
    pushed. On conflict the merge is aborted and ``(False, output)`` returned.
    """
    if not target_is_remote and target == current_branch(repo_path):
        return merge_branch(repo_path, source_branch)

    parent = tempfile.mkdtemp(prefix="loom-merge-")
    wt = os.path.join(parent, "wt")
    try:
        if target_is_remote:
            local_name = target.split("/", 1)[1]
            add = _run(repo_path, "worktree", "add", "-b", local_name, wt, target)
        else:
            add = _run(repo_path, "worktree", "add", wt, target)
        if add.returncode != 0:
            return False, (add.stdout + add.stderr).strip()
        proc = _run(wt, "merge", "--no-ff", "-m", f"Merge {source_branch}", source_branch)
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0:
            _run(wt, "merge", "--abort")
            return False, out
        return True, out
    finally:
        _run(repo_path, "worktree", "remove", "--force", wt)
        shutil.rmtree(parent, ignore_errors=True)


def remove_worktree(repo_path: str, workspace_path: str) -> None:
    _run(repo_path, "worktree", "remove", "--force", workspace_path)
