"""Tests for inbox path parsing in the watcher."""
import pytest
from daemon.watcher import parse_inbox_path


def test_parse_flat_inbox_path():
    """Old layout: inbox/<project>/<file> — user is None."""
    project, user, filename = parse_inbox_path(
        "/home/user/.loom/inbox/my-project/finding-1.md"
    )
    assert project == "my-project"
    assert user is None
    assert filename == "finding-1.md"


def test_parse_user_inbox_path():
    """New layout: inbox/<project>/<user>/<file> — user is captured."""
    project, user, filename = parse_inbox_path(
        "/home/user/.loom/inbox/my-project/alice/finding-1.md"
    )
    assert project == "my-project"
    assert user == "alice"
    assert filename == "finding-1.md"


def test_parse_processed_subdirectory():
    """Paths under .processed/ still extract project and user."""
    project, user, filename = parse_inbox_path(
        "/home/user/.loom/inbox/my-project/bob/.processed/register.json"
    )
    assert project == "my-project"
    assert user == "bob"
    assert filename == "register.json"


def test_parse_path_without_inbox():
    """Paths that don't contain 'inbox' return safe defaults."""
    project, user, filename = parse_inbox_path("/tmp/some-file.md")
    assert project == "unknown"
    assert user is None
