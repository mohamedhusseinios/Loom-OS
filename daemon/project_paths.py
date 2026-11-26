"""Safe project ids and inbox paths (shared by API, MCP, CLI)."""

from __future__ import annotations

import os
from pathlib import Path


def safe_project_id(project: str) -> str:
    """Reject path traversal / absolute segments in a project id."""
    if not project or not isinstance(project, str):
        raise ValueError("project id required")
    name = project.strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
        raise ValueError(f"invalid project id: {project!r}")
    if os.sep in name or (os.altsep and os.altsep in name):
        raise ValueError(f"invalid project id: {project!r}")
    return name


def project_inbox_dir(inbox_base: str | Path, project: str) -> Path:
    """Return ``inbox_base / project``, ensuring the result stays under base."""
    base = Path(inbox_base).expanduser().resolve()
    safe = safe_project_id(project)
    path = (base / safe).resolve()
    if path != base and base not in path.parents:
        raise ValueError(f"project inbox escapes inbox root: {project!r}")
    return path
