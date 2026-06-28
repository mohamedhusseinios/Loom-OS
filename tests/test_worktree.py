import subprocess
from pathlib import Path

import pytest

from daemon import worktree


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A git repo on branch 'main' with one commit."""
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t.test")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("hello\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


def test_create_commit_diff_merge_roundtrip(repo, tmp_path):
    ws = tmp_path / "ws" / "task-abc"
    worktree.create_worktree(str(repo), str(ws), "loom/task-abc", base_ref="main")
    assert ws.exists()
    assert worktree.current_branch(str(repo)) == "main"

    # Agent edits a file in the worktree.
    (ws / "new.txt").write_text("agent work\n")
    made = worktree.commit_all(str(ws), "loom task abc")
    assert made is True

    diff = worktree.branch_diff(str(repo), "main", "loom/task-abc")
    assert "new.txt" in diff
    assert "agent work" in diff

    ok, _out = worktree.merge_branch(str(repo), "loom/task-abc")
    assert ok is True
    assert (repo / "new.txt").read_text() == "agent work\n"

    worktree.remove_worktree(str(repo), str(ws))
    assert not ws.exists()


def test_commit_all_returns_false_when_no_changes(repo, tmp_path):
    ws = tmp_path / "ws" / "task-empty"
    worktree.create_worktree(str(repo), str(ws), "loom/task-empty", base_ref="main")
    assert worktree.commit_all(str(ws), "noop") is False


def test_list_branches_shape_and_exclusions(repo):
    _git(repo, "branch", "develop")
    _git(repo, "branch", "loom/task-zzz")
    data = worktree.list_branches(str(repo))
    assert data["current"] == "main"
    names = [b["name"] for b in data["branches"]]
    assert "main" in names
    assert "develop" in names
    assert "loom/task-zzz" not in names          # task branches excluded
    assert all(b["remote"] is False for b in data["branches"])  # no remotes here


def test_merge_branch_into_non_checked_out_branch(repo, tmp_path):
    # 'develop' exists but is not checked out (repo is on 'main').
    _git(repo, "branch", "develop")
    ws = tmp_path / "ws" / "task-m"
    worktree.create_worktree(str(repo), str(ws), "loom/task-m", base_ref="main")
    (ws / "feature.txt").write_text("work\n")
    worktree.commit_all(str(ws), "task m")

    ok, _out = worktree.merge_branch_into(str(repo), "loom/task-m", "develop")
    assert ok is True
    # Main checkout untouched: still on main, no feature.txt in its working tree.
    assert worktree.current_branch(str(repo)) == "main"
    assert not (repo / "feature.txt").exists()
    # 'develop' advanced and now contains the merged file.
    assert "work" in _git(repo, "show", "develop:feature.txt")
    # No throwaway merge worktree left behind.
    assert "loom-merge" not in _git(repo, "worktree", "list")
    worktree.remove_worktree(str(repo), str(ws))


def test_merge_branch_into_conflict_aborts(repo, tmp_path):
    # Put a conflicting change on 'develop'.
    _git(repo, "checkout", "-b", "develop")
    (repo / "README.md").write_text("develop change\n")
    _git(repo, "commit", "-am", "develop edit")
    _git(repo, "checkout", "main")
    # Task branch edits the same file differently.
    ws = tmp_path / "ws" / "task-c"
    worktree.create_worktree(str(repo), str(ws), "loom/task-c", base_ref="main")
    (ws / "README.md").write_text("task change\n")
    worktree.commit_all(str(ws), "task c")

    ok, out = worktree.merge_branch_into(str(repo), "loom/task-c", "develop")
    assert ok is False
    assert "conflict" in out.lower()
    # Clean state: still on main, working tree clean, no leftover worktree.
    assert worktree.current_branch(str(repo)) == "main"
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert "loom-merge" not in _git(repo, "worktree", "list")
    worktree.remove_worktree(str(repo), str(ws))


def test_merge_branch_into_remote_target_creates_local_no_push(repo, tmp_path):
    # Bare remote cloned from repo, with a 'feature' branch at main's commit
    # (shared history, so the later merge is clean rather than "unrelated").
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(repo), str(bare)],
                   check=True, capture_output=True, text=True)
    _git(bare, "branch", "feature", "main")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "fetch", "origin")
    # Task branch forks from main and adds a file.
    ws = tmp_path / "ws" / "task-r"
    worktree.create_worktree(str(repo), str(ws), "loom/task-r", base_ref="main")
    (ws / "feature.txt").write_text("remote work\n")
    worktree.commit_all(str(ws), "task r")

    ok, _out = worktree.merge_branch_into(
        str(repo), "loom/task-r", "origin/feature", target_is_remote=True
    )
    assert ok is True
    # A local 'feature' branch was created and contains the merged file.
    assert "feature" in _git(repo, "branch", "--list", "feature")
    assert "remote work" in _git(repo, "show", "feature:feature.txt")
    # Nothing was pushed: the bare remote's 'feature' has no feature.txt.
    pushed = subprocess.run(["git", "-C", str(bare), "show", "feature:feature.txt"],
                            capture_output=True, text=True)
    assert pushed.returncode != 0
    worktree.remove_worktree(str(repo), str(ws))
