"""Shared agent context — the knowledge fabric all agents read from.

Generates a ``SHARED_CONTEXT.md`` file in each project's ``.loom/``
directory that every agent can include in its working context.  The file
is regenerated whenever the graph is built or a finding is ingested, so
agents always see the latest shared knowledge.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


async def generate_shared_context(
    project_id: str,
    project_path: str,
    graph_engine,
    registry,
) -> str:
    """Build a Markdown context document for the project and write it to
    ``<project_path>/.loom/SHARED_CONTEXT.md``.

    Returns the file path that was written.
    """
    loom_dir = Path(project_path) / ".loom"
    loom_dir.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []

    # ── Header ─────────────────────────────────────────────────────────
    sections.append(_header(project_id))

    # ── Graph overview ─────────────────────────────────────────────────
    graph_section = await _graph_overview(project_path, graph_engine)
    if graph_section:
        sections.append(graph_section)

    # ── Knowledge sources ──────────────────────────────────────────────
    ks_section = await _knowledge_sources_section(project_path)
    if ks_section:
        sections.append(ks_section)

    # ── Recent findings ────────────────────────────────────────────────
    findings_section = await _recent_findings(project_id)
    if findings_section:
        sections.append(findings_section)

    # ── Agent roster ───────────────────────────────────────────────────
    roster_section = await _agent_roster(project_id, registry)
    if roster_section:
        sections.append(roster_section)

    # ── How to use ─────────────────────────────────────────────────────
    sections.append(_usage_instructions(project_id))

    # ── Footer ─────────────────────────────────────────────────────────
    sections.append(_footer())

    content = "\n\n".join(sections) + "\n"

    out_path = loom_dir / "SHARED_CONTEXT.md"
    out_path.write_text(content)
    logger.info("Shared context written: %s (%d bytes)", out_path, len(content))

    return str(out_path)


# ── Section builders ────────────────────────────────────────────────────


def _header(project_id: str) -> str:
    return (
        f"# Loom OS — Shared Agent Context\n\n"
        f"> **Project:** `{project_id}`\n"
        f"> **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"> **Auto-regenerated** on graph builds and finding ingestions.\n"
        f"> All agents registered with this project share this knowledge fabric.\n"
    )


async def _graph_overview(project_path: str, graph_engine) -> str:
    """Summarise the knowledge graph: stats + top communities + key symbols."""
    try:
        stats = await graph_engine.get_stats(project_path)
        if stats.nodes == 0:
            return "## Knowledge Graph\n\n_No graph built yet. Dispatch a build from the Loom dashboard._\n"

        communities = await graph_engine.get_communities(project_path)
        topo = await graph_engine.get_topology(project_path)

        # Top communities
        community_lines = ""
        for c in communities[:10]:
            community_lines += f"| {c['name']} | {c['size']} |\n"

        # Entry-point symbols (file-level nodes with highest degree)
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        entry_points = ""
        if graph_path.exists():
            data = json.loads(graph_path.read_text())
            nodes = data.get("nodes", [])
            links = data.get("links", data.get("edges", []))
            degree: dict[str, int] = {}
            for lnk in links:
                s = lnk.get("source", "")
                t = lnk.get("target", "")
                degree[s] = degree.get(s, 0) + 1
                degree[t] = degree.get(t, 0) + 1
            # Pick top 15 by degree
            top_ids = sorted(degree, key=lambda k: degree[k], reverse=True)[:15]
            node_map = {n["id"]: n for n in nodes}
            for nid in top_ids:
                node = node_map.get(nid, {})
                label = node.get("label", nid)
                fpath = node.get("source_file", "")
                entry_points += f"| `{label}` | {fpath} | {degree[nid]} |\n"

        return (
            f"## Knowledge Graph\n\n"
            f"- **{stats.nodes}** nodes · **{stats.edges}** edges · **{stats.communities}** communities\n\n"
            f"### Top Communities\n\n"
            f"| Community | Size |\n|---|---|\n"
            f"{community_lines}\n"
            f"### Key Symbols (by connectivity)\n\n"
            f"| Symbol | File | Connections |\n|---|---|---|\n"
            f"{entry_points}\n"
        )
    except Exception as exc:
        logger.warning("Graph overview failed: %s", exc)
        return "## Knowledge Graph\n\n_Unable to read graph data._\n"


async def _knowledge_sources_section(project_path: str) -> str:
    """List discovered knowledge sources (CLAUDE.md, AGENTS.md, etc.)."""
    try:
        from daemon.project_knowledge import discover_knowledge_sources
        sources = discover_knowledge_sources(project_path)
        found = [s for s in sources if s.found]
        if not found:
            return ""

        lines = ""
        for s in found:
            lines += f"| {s.display_name} | `{s.path}` | {', '.join(s.used_by[:3])} |\n"

        return (
            f"## Knowledge Sources\n\n"
            f"| Source | Path | Used by |\n|---|---|---|\n"
            f"{lines}\n"
        )
    except Exception as exc:
        logger.warning("Knowledge sources section failed: %s", exc)
        return ""


async def _recent_findings(project_id: str) -> str:
    """List recent agent findings from the inbox."""
    try:
        inbox_dir = Path(os.path.expanduser(f"~/.loom/inbox/{project_id}"))
        processed_dir = inbox_dir / ".processed"
        finding_files: list[Path] = []
        for d in (inbox_dir, processed_dir):
            if d.exists():
                finding_files.extend(sorted(d.glob("finding-*.md"), key=lambda p: p.stat().st_mtime, reverse=True))
        if not finding_files:
            return ""

        lines = ""
        for fp in finding_files[:10]:
            content = fp.read_text()[:500]
            # Extract first heading or first sentence
            title = fp.stem.replace("finding-", "", 1).replace("-", " ").title()
            lines += f"- **{title}** — `{fp.name}`\n"

        return (
            f"## Recent Agent Findings\n\n"
            f"{lines}\n"
            f"_Full findings: `~/.loom/inbox/{project_id}/.processed/`_\n"
        )
    except Exception as exc:
        logger.warning("Recent findings section failed: %s", exc)
        return ""


async def _agent_roster(project_id: str, registry) -> str:
    """List agents registered for this project."""
    try:
        agents = await registry.list_agents(project_id)
        if not agents:
            return ""

        lines = ""
        for a in agents:
            status_icon = {"online": "🟢", "offline": "⚫", "working": "🟡"}.get(
                a.status.value, "⚫"
            )
            lines += f"| {status_icon} {a.agent_name} | {a.version} | {', '.join(a.capabilities[:5])} |\n"

        return (
            f"## Agent Roster\n\n"
            f"| Agent | Version | Capabilities |\n|---|---|---|\n"
            f"{lines}\n"
        )
    except Exception as exc:
        logger.warning("Agent roster section failed: %s", exc)
        return ""


def _usage_instructions(project_id: str) -> str:
    return (
        f"## How Agents Use This Context\n\n"
        f"**Include this file in your agent's working context.**\n\n"
        f"- **Claude Code:** add to `CLAUDE.md` or read with `/loom-context`\n"
        f"- **Codex:** add to `AGENTS.md` or read at session start\n"
        f"- **Direct read:** `cat .loom/SHARED_CONTEXT.md`\n"
        f"- **API query:** `GET /api/projects/{project_id}/graph/topology`\n"
        f"- **Graphify query:** `graphify query \"your question\"` from the project root\n"
        f"- **Inbox:** drop `finding-*.md` files to share discoveries with other agents\n"
    )


def _footer() -> str:
    return (
        "---\n"
        "_Generated by Loom OS — the unified agent memory fabric._\n"
    )
