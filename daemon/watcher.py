"""Filesystem watcher for the agent inbox."""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Awaitable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, str | None, str], Awaitable[None]]  # (project, user, filepath)


def parse_inbox_path(path: str) -> tuple[str, str | None, str]:
    """Extract (project, user, filename) from an inbox file path.

    Supports both layouts:
    - Flat:   inbox/<project>/<file>           -> (project, None, file)
    - User:   inbox/<project>/<user>/<file>    -> (project, user, file)

    Paths under .processed/ are handled correctly (user is still captured).
    Returns ("unknown", None, filename) if 'inbox' is not in the path.
    """
    parts = Path(path).parts
    try:
        inbox_idx = parts.index("inbox")
    except ValueError:
        return ("unknown", None, Path(path).name)

    remaining = parts[inbox_idx + 1:]
    if len(remaining) >= 3:
        project = remaining[0]
        user = remaining[1]
        filename = remaining[-1]
    elif len(remaining) == 2:
        project = remaining[0]
        user = None
        filename = remaining[1]
    elif len(remaining) == 1:
        project = remaining[0]
        user = None
        filename = ""
    else:
        project = "unknown"
        user = None
        filename = ""
    return (project, user, filename)


class InboxHandler(FileSystemEventHandler):
    """Watchdog handler that fires callbacks on inbox file events."""

    def __init__(self, callback: EventHandler, loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        self._dispatch(event.src_path)

    def on_modified(self, event: FileModifiedEvent):
        if event.is_directory:
            return
        self._dispatch(event.src_path)

    def _dispatch(self, filepath: str):
        project, user, _ = parse_inbox_path(filepath)
        asyncio.run_coroutine_threadsafe(
            self.callback(project, user, filepath), self.loop
        )


class InboxWatcher:
    """Watches ~/.loom/inbox/ for new files."""

    def __init__(self, inbox_path: str = "~/.loom/inbox"):
        self.inbox_path = Path(inbox_path).expanduser().resolve()
        self.observer: Optional[Observer] = None
        self._handler: Optional[InboxHandler] = None

    def start(self, callback: EventHandler, loop: asyncio.AbstractEventLoop):
        """Start watching the inbox directory."""
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self._handler = InboxHandler(callback, loop)
        self.observer = Observer()
        self.observer.schedule(self._handler, str(self.inbox_path), recursive=True)
        self.observer.start()
        logger.info(f"Watcher started on {self.inbox_path}")

    def stop(self):
        """Stop the watcher."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logger.info("Watcher stopped")

    @property
    def is_running(self) -> bool:
        return self.observer is not None and self.observer.is_alive()
