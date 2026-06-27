"""loom worker — autonomously runs Claude Code on Running tasks.

A first-party Loom process (not a third-party agent): it talks to the
daemon over HTTP, runs `claude -p` headless in an isolated git worktree,
and writes results + findings back. Single task at a time (V1).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from daemon.worktree import create_worktree, commit_all, current_branch

logger = logging.getLogger("loom.worker")


@dataclass
class ClaudeResult:
    text: str
    session_id: str | None
    is_error: bool


class Worker:
    def __init__(
        self,
        project: str,
        agent: str,
        project_path: str,
        base_url: str = "http://127.0.0.1:8472",
        model: str | None = None,
        max_turns: int = 30,
        poll_interval: float = 2.5,
    ):
        self.project = project
        self.agent = agent
        self.project_path = project_path
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_turns = max_turns
        self.poll_interval = poll_interval
        self.workspaces_dir: str = os.path.expanduser("~/.loom/workspaces")
        self._inflight: set[str] = set()
        self._stop: bool = False

    @property
    def agent_id(self) -> str:
        return f"{self.agent}-{self.project}"

    def eligible(self, tasks: list[dict]) -> list[dict]:
        return [
            t for t in tasks
            if t.get("assignee") == self.agent_id and t.get("id") not in self._inflight
        ]
