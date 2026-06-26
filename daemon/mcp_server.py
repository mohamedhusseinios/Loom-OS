"""MCP server exposing the Agentic OS API as callable tools.

Stdio transport for Claude Desktop, Cursor, Cline, and any MCP-compatible
client.  Tools read directly from the filesystem (~/.loom) so they work
with zero configuration — no running daemon required.

Usage (stdio)::

    python -m daemon.mcp_server

Claude Desktop config::

    {
      "mcpServers": {
        "agentic-os": {
          "command": "python",
          "args": ["-m", "daemon.mcp_server"]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="agentic-os",
    instructions="Agentic OS knowledge fabric — search graphs, recall patterns, add findings.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_db_path(loom_dir: str | None = None) -> Path:
    base = Path(loom_dir) if loom_dir else Path(os.path.expanduser("~/.loom"))
    return base / "state.db"


def _project_inbox(project: str, loom_dir: str | None = None) -> Path:
    base = Path(loom_dir) if loom_dir else Path(os.path.expanduser("~/.loom"))
    return base / "inbox" / project


def _find_project_path(project: str, loom_dir: str | None = None) -> str | None:
    import sqlite3
    db = _state_db_path(loom_dir)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT project_path FROM projects WHERE project_id = ?", (project,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _graph_json(project_path: str) -> dict | None:
    graph_path = Path(project_path) / "graphify-out" / "graph.json"
    if not graph_path.exists():
        return None
    with open(graph_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="list_projects",
    annotations={"title": "List Projects", "readOnlyHint": True},
)
def list_projects(loom_dir: str | None = None) -> list[dict]:
    """Return all tracked projects with their graph stats."""
    import sqlite3
    db = _state_db_path(loom_dir)
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT project_id, project_name, project_path, node_count,"
            " edge_count, community_count, last_graph_update, total_findings"
            " FROM projects ORDER BY project_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@mcp.tool(
    name="get_project_graph",
    annotations={"title": "Get Project Graph", "readOnlyHint": True},
)
def get_project_graph(project: str, loom_dir: str | None = None) -> dict:
    """Return the full graph topology (nodes + edges) for a project."""
    project_path = _find_project_path(project, loom_dir)
    if project_path is None:
        return {"error": f"Project '{project}' not found", "nodes": [], "edges": []}

    graph = _graph_json(project_path)
    if graph is None:
        return {"error": "No graph built for this project", "nodes": [], "edges": []}

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    result_nodes = []
    for n in nodes:
        result_nodes.append({
            "id": n.get("id", ""),
            "label": n.get("name", n.get("id", "")),
            "kind": n.get("kind", "Unknown"),
            "community": n.get("community_id", 0),
            "file": n.get("file", ""),
        })

    result_edges = []
    for e in edges:
        result_edges.append({
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "kind": e.get("kind", "references"),
        })

    return {"nodes": result_nodes, "edges": result_edges}


@mcp.tool(
    name="search_knowledge_graph",
    annotations={"title": "Search Knowledge Graph", "readOnlyHint": True},
)
def search_knowledge_graph(query: str, project: str, loom_dir: str | None = None) -> list[dict]:
    """Search the knowledge graph and inbox findings for a project."""
    results: list[dict] = []

    # 1. Search graph.json
    project_path = _find_project_path(project, loom_dir)
    if project_path:
        graph = _graph_json(project_path)
        if graph:
            query_lower = query.lower()
            for node in graph.get("nodes", []):
                name = (node.get("name") or node.get("label", "")).lower()
                if query_lower in name:
                    kind = node.get("kind", "Unknown")
                    results.append({
                        "id": node.get("id", ""),
                        "name": node.get("name", ""),
                        "kind": kind,
                        "source": "graph",
                        "relevance": "high" if query_lower == name else "medium",
                    })

    # 2. Search inbox findings
    inbox = _project_inbox(project, loom_dir)
    if inbox.exists():
        query_lower = query.lower()
        for f_path in sorted(
            inbox.glob("finding-*.md"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        ):
            try:
                content = f_path.read_text()
            except OSError:
                continue
            if query_lower in content.lower():
                lines = content.split("\n")
                body_start = 0
                if lines and lines[0].strip() == "---":
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip() == "---":
                            body_start = i + 1
                            break
                body = "\n".join(lines[body_start:]).strip()[:300]
                results.append({
                    "id": f_path.stem,
                    "text": body,
                    "source": "finding",
                    "relevance": "medium",
                })

    return results[:10]


@mcp.tool(
    name="add_to_memory",
    annotations={"title": "Add to Memory", "readOnlyHint": False},
)
def add_to_memory(
    finding: str,
    project: str,
    agent: str = "mcp-client",
    finding_type: str = "general",
    loom_dir: str | None = None,
) -> dict:
    """Write a finding to the project inbox so other agents can recall it.

    Args:
        finding: The finding text (should start with FOUND:, PATTERN:, or DECISION:).
        project: The project id.
        agent: The agent making this addition.
        finding_type: Type of finding (e.g. "code-analysis", "bug-report").
    """
    inbox = _project_inbox(project, loom_dir)
    inbox.mkdir(parents=True, exist_ok=True)

    # Prefix if not already structured
    prefixes = ("FOUND:", "PATTERN:", "DECISION:")
    if not any(finding.strip().startswith(p) for p in prefixes):
        if finding_type.upper() in ("FOUND", "PATTERN", "DECISION"):
            finding = f"{finding_type.upper()}: {finding}"
        else:
            finding = f"FOUND: {finding}"

    finding_id = str(uuid.uuid4())[:8]
    finding_path = inbox / f"finding-{finding_id}.md"
    finding_path.write_text(
        f"""---
agent: {agent}
project: {project}
timestamp: {datetime.now(timezone.utc).isoformat()}
confidence: medium
---
{finding}
"""
    )
    return {"status": "stored", "id": finding_id, "path": str(finding_path)}


@mcp.tool(
    name="query_graph",
    annotations={"title": "Query Graph", "readOnlyHint": True},
)
def query_graph(question: str, project: str, loom_dir: str | None = None) -> dict:
    """Query the project knowledge graph for matching entities.

    Args:
        question: Natural language question about the codebase.
        project: The project id.
    """
    project_path = _find_project_path(project, loom_dir)
    if project_path is None:
        return {"results": [], "hint": f"Project '{project}' not tracked"}

    graph = _graph_json(project_path)
    if graph is None:
        return {"results": [], "hint": "No graph built for this project"}

    keywords = question.lower().split()
    results = []
    for node in graph.get("nodes", []):
        name = (node.get("name") or node.get("label", "")).lower()
        kind = node.get("kind", "")
        if any(kw in name for kw in keywords):
            results.append({
                "name": node.get("name", ""),
                "kind": kind,
                "file": node.get("file", ""),
                "id": node.get("id", ""),
            })

    return {"results": results[:20], "total": len(results)}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    """Run the MCP server on stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
