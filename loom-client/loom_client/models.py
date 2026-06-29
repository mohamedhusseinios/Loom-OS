"""Pydantic schemas for Loom inbox files.

Ported from daemon/models.py — the single source of truth.
If daemon schemas change, update these to match.
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class RegisterPayload(BaseModel):
    agent: str
    version: str = "1.0"
    project: str
    project_path: str
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatPayload(BaseModel):
    agent: str
    project: str
    status: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FindingPayload(BaseModel):
    """Frontmatter + body for a finding-*.md file."""
    agent: str
    project: str
    type: str = "general"  # code-analysis | architecture-decision | bug-report | general
    files: list[str] = Field(default_factory=list)
    timestamp: Optional[datetime] = None
    title: str = ""  # used for the filename
    body: str = ""   # markdown body after frontmatter


class TaskPayload(BaseModel):
    type: str = "task"
    task_id: str
    target_agent: str
    instruction: str
    priority: str = "medium"
    dispatched_by: str = "sdk"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))