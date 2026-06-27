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
