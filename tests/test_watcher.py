"""Tests for the Watcher."""
import asyncio
import pytest
from daemon.watcher import InboxWatcher


@pytest.mark.asyncio
async def test_watcher_detects_new_file(tmp_path):
    """Watcher should fire callback when a file is created."""
    received = []

    async def callback(project: str, filepath: str):
        received.append((project, filepath))

    inbox = tmp_path / "inbox"
    inbox.mkdir()

    watcher = InboxWatcher(str(inbox))
    loop = asyncio.get_running_loop()
    watcher.start(callback, loop)

    # Write a file
    proj_dir = inbox / "test-project"
    proj_dir.mkdir()
    (proj_dir / "finding.md").write_text("# Test finding")

    # Wait for watchdog to pick it up
    await asyncio.sleep(0.5)

    watcher.stop()
    assert len(received) >= 1
    assert received[0][0] == "test-project"
