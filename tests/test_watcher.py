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


def test_inbox_handler_ignores_processed_files():
    """InboxHandler should ignore files created or modified inside .processed."""
    from daemon.watcher import InboxHandler
    from watchdog.events import FileCreatedEvent
    dispatched = []

    async def fake_cb(project, filepath, user=None):
        dispatched.append(filepath)

    handler = InboxHandler(fake_cb, None)
    event = FileCreatedEvent("/home/user/.loom/inbox/proj/.processed/finding-1.md")
    handler.on_created(event)
    assert dispatched == []


@pytest.mark.asyncio
async def test_watcher_dispatches_filepath_before_user(tmp_path):
    """InboxHandler must call callback(project, filepath, user) — not (project, user, filepath).

    Regression: team-mode path parsing put user in the second slot, so the router
    treated None/user as the filepath and never processed flat inbox drops.
    """
    import asyncio
    from daemon.watcher import InboxHandler
    from watchdog.events import FileCreatedEvent

    seen = []

    async def capture(project, filepath, user=None):
        seen.append((project, filepath, user))

    loop = asyncio.get_running_loop()
    handler = InboxHandler(capture, loop)
    path = str(tmp_path / "inbox" / "my-project" / "finding-1.md")
    (tmp_path / "inbox" / "my-project").mkdir(parents=True)
    (tmp_path / "inbox" / "my-project" / "finding-1.md").write_text("x")

    handler.on_created(FileCreatedEvent(path))
    await asyncio.sleep(0.05)

    assert len(seen) == 1
    project, filepath, user = seen[0]
    assert project == "my-project"
    assert filepath == path
    assert user is None


@pytest.mark.asyncio
async def test_watcher_to_router_processes_finding(tmp_path):
    """End-to-end: InboxHandler arity matches Router.handle_file and moves the file."""
    import asyncio
    import json
    from daemon.watcher import InboxHandler
    from daemon.router import Router
    from daemon.registry import AgentRegistry
    from daemon.graph_engine import GraphEngine
    from watchdog.events import FileCreatedEvent

    db = AgentRegistry(str(tmp_path / "state.db"))
    await db.initialize()
    await db.upsert_project("proj", str(tmp_path / "repo"))
    router = Router(db, GraphEngine())
    loop = asyncio.get_running_loop()
    handler = InboxHandler(router.handle_file, loop)

    inbox = tmp_path / "inbox" / "proj"
    inbox.mkdir(parents=True)
    finding = inbox / "finding-abc.md"
    finding.write_text(
        "---\nagent: claude-code\nproject: proj\ntype: general\n---\nhello auth\n"
    )

    handler.on_created(FileCreatedEvent(str(finding)))
    for _ in range(50):
        if not finding.exists():
            break
        await asyncio.sleep(0.02)

    assert not finding.exists()
    assert (inbox / ".processed" / "finding-abc.md").exists()
    await db.close()

