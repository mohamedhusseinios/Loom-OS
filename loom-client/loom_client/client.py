"""LoomClient — validated one-liners for the Loom inbox protocol.

Each method validates the payload with Pydantic and writes the file to the
correct inbox path. The raw-file path stays fully supported — this is a
convenience wrapper, not a replacement.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from loom_client.models import (
    RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload,
)


def _slugify(text: str) -> str:
    """Convert a title to a filename-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip())
    return slug.strip("-").lower() or "untitled"


class LoomClient:
    """Write validated inbox files to the Loom daemon's filesystem inbox."""

    def __init__(self, loom_dir: str | None = None):
        self.loom_dir = Path(loom_dir or os.path.expanduser("~/.loom"))

    def _inbox(self, project: str) -> Path:
        d = self.loom_dir / "inbox" / project
        d.mkdir(parents=True, exist_ok=True)
        return d

    def register(
        self,
        project: str,
        agent: str,
        project_path: str,
        capabilities: list[str] | None = None,
        version: str = "1.0",
    ) -> Path:
        """Write register.json to the project inbox."""
        payload = RegisterPayload(
            agent=agent,
            version=version,
            project=project,
            project_path=project_path,
            capabilities=capabilities or [],
        )
        path = self._inbox(project) / "register.json"
        path.write_text(json.dumps(payload.model_dump(), indent=2))
        return path

    def heartbeat(
        self,
        project: str,
        agent: str,
        status: str = "",
    ) -> Path:
        """Write heartbeat.json to the project inbox."""
        payload = HeartbeatPayload(agent=agent, project=project, status=status)
        path = self._inbox(project) / "heartbeat.json"
        path.write_text(json.dumps(payload.model_dump(), indent=2, default=str))
        return path

    def finding(
        self,
        project: str,
        agent: str,
        title: str,
        body: str,
        files: list[str] | None = None,
        type: str = "general",
    ) -> Path:
        """Write a finding-<slug>.md file with YAML frontmatter + body."""
        payload = FindingPayload(
            agent=agent,
            project=project,
            type=type,
            files=files or [],
            title=title,
            body=body,
        )
        slug = _slugify(title)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"finding-{slug}-{timestamp}.md"
        path = self._inbox(project) / filename

        frontmatter = {
            "agent": payload.agent,
            "project": payload.project,
            "type": payload.type,
            "files": payload.files,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{payload.body}\n"
        path.write_text(content)
        return path

    def task(
        self,
        project: str,
        title: str,
        instruction: str,
        target_agent: str,
        task_id: str | None = None,
        priority: str = "medium",
    ) -> Path:
        """Write a task-<id>.json file to the project inbox."""
        if task_id is None:
            task_id = str(uuid.uuid4())[:12]
        payload = TaskPayload(
            task_id=task_id,
            target_agent=target_agent,
            instruction=instruction,
            priority=priority,
        )
        path = self._inbox(project) / f"task-{task_id}.json"
        path.write_text(json.dumps(payload.model_dump(), indent=2, default=str))
        return path