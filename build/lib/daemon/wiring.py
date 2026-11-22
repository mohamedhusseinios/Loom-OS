"""Zero-config wiring for AI coding agents and MCP clients.

Injects idempotent instruction blocks into CLAUDE.md, AGENTS.md, and .mcp.json
so Claude Code, Codex, Cursor, and Gemini CLI automatically discover Loom OS.
"""

from __future__ import annotations

import json
from pathlib import Path

LOOM_BLOCK_START = "<!-- LOOM-OS:START -->"
LOOM_BLOCK_END = "<!-- LOOM-OS:END -->"


def render_loom_block(project: str) -> str:
    """Render concise markdown instructions for coding agents."""
    return f"""{LOOM_BLOCK_START}
## Loom OS Shared Agent Memory Fabric
This project is connected to Loom OS.
- **Shared Memory:** Read `.loom/SHARED_CONTEXT.md` at session start for architecture, active agents, and cross-session knowledge.
- **Record Findings:** Drop discoveries into `~/.loom/inbox/{project}/finding-<slug>.md` with frontmatter:
  ```yaml
  ---
  agent: <your-name>
  project: {project}
  type: pattern | bug-report | gotcha
  files: [path/to/relevant/file]
  ---
  ```
- **Record Decisions:** Drop architecture decisions into `~/.loom/inbox/{project}/decision-<slug>.md`.
{LOOM_BLOCK_END}"""


def upsert_markdown_block(filepath: Path, project: str) -> bool:
    """Create or update the Loom OS instructions block in a markdown file.

    Returns True if the file was created or modified, False if already up-to-date.
    """
    block = render_loom_block(project)
    if filepath.exists():
        content = filepath.read_text()
        if LOOM_BLOCK_START in content and LOOM_BLOCK_END in content:
            before = content.split(LOOM_BLOCK_START)[0]
            after = content.split(LOOM_BLOCK_END)[1]
            new_content = f"{before}{block}{after}"
            if new_content == content:
                return False
            filepath.write_text(new_content)
            return True
        else:
            sep = "\n\n" if content.strip() else ""
            filepath.write_text(f"{content.rstrip()}{sep}{block}\n")
            return True
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(f"{block}\n")
        return True


def upsert_mcp_config(project_root: Path) -> bool:
    """Merge Loom OS into .mcp.json under mcpServers.

    Returns True if .mcp.json was created or modified, False if already configured.
    """
    mcp_path = project_root / ".mcp.json"
    data = {}
    if mcp_path.exists():
        try:
            data = json.loads(mcp_path.read_text())
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    servers = data.setdefault("mcpServers", {})
    loom_cfg = {"command": "loom-mcp", "args": []}
    if servers.get("loom-os") == loom_cfg:
        return False

    servers["loom-os"] = loom_cfg
    mcp_path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def wire_project(project: str, project_path: str) -> dict:
    """Wire agent instructions and MCP config into a project directory."""
    root = Path(project_path)
    root.mkdir(parents=True, exist_ok=True)

    c_mod = upsert_markdown_block(root / "CLAUDE.md", project)
    a_mod = upsert_markdown_block(root / "AGENTS.md", project)
    m_mod = upsert_mcp_config(root)

    any_updated = c_mod or a_mod or m_mod
    return {
        "project": project,
        "project_path": str(root),
        "files": ["CLAUDE.md", "AGENTS.md", ".mcp.json"],
        "updated": any_updated,
        "idempotent": not any_updated,
    }
