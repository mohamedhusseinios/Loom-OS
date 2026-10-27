"""Cross-project graph federation engine (Feature #5).

Provides org-wide, read-only queries and symbol discovery across all
registered projects without violating per-project write isolation.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any

from daemon.graph_engine import GraphEngine


class FederatedIndex:
    """Read-only federated knowledge index spanning multiple projects."""

    def __init__(self, engine: GraphEngine | None = None):
        self.engine = engine or GraphEngine()
        self._projects: dict[str, str] = {}  # project_id -> project_path
        self._nodes_by_project: dict[str, list[dict]] = {}
        self._degrees_by_project: dict[str, dict[str, int]] = {}
        self._stats: dict[str, int] = {
            "projects_indexed": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "shared_symbols": 0,
        }

    async def build_index(self, projects: list[dict[str, Any] | Any]) -> dict[str, int]:
        """Index nodes, edges, and symbol frequencies across projects."""
        self._projects.clear()
        self._nodes_by_project.clear()
        self._degrees_by_project.clear()

        total_nodes = 0
        total_edges = 0
        symbol_project_map: dict[str, set[str]] = defaultdict(set)

        for p in projects:
            p_id = p["project_id"] if isinstance(p, dict) else getattr(p, "project_id", getattr(p, "name", None))
            p_path = p["project_path"] if isinstance(p, dict) else getattr(p, "project_path", None)
            if not p_id or not p_path:
                continue

            gpath = Path(p_path) / "graphify-out" / "graph.json"
            if not gpath.exists():
                continue

            self._projects[p_id] = p_path
            graph = await asyncio.to_thread(GraphEngine._read_graph_json, gpath)
            nodes = graph.get("nodes", [])
            links = graph.get("links", graph.get("edges", []))

            self._nodes_by_project[p_id] = nodes
            degrees: dict[str, int] = defaultdict(int)
            for link in links:
                s = link.get("source")
                t = link.get("target")
                if s:
                    degrees[s] += 1
                if t:
                    degrees[t] += 1
            self._degrees_by_project[p_id] = degrees

            total_nodes += len(nodes)
            total_edges += len(links)

            for n in nodes:
                name = (n.get("label") or n.get("name") or n.get("id", "").split(".")[-1]).strip()
                if name:
                    symbol_project_map[name.lower()].add(p_id)

        shared = sum(1 for projs in symbol_project_map.values() if len(projs) >= 2)
        self._stats = {
            "projects_indexed": len(self._projects),
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "shared_symbols": shared,
        }
        return self._stats

    async def cross_project_references(self, symbol: str) -> list[dict]:
        """Find references to symbol across all indexed projects."""
        if not symbol or not symbol.strip():
            return []
        sym_lower = symbol.strip().lower()
        refs: list[dict] = []

        for p_id, nodes in self._nodes_by_project.items():
            degrees = self._degrees_by_project.get(p_id, {})
            for n in nodes:
                n_id = str(n.get("id", ""))
                label = str(n.get("label") or n.get("name") or "")
                tail = n_id.split(".")[-1]
                if (
                    sym_lower == label.lower()
                    or sym_lower == n_id.lower()
                    or sym_lower == tail.lower()
                ):
                    refs.append({
                        "project": p_id,
                        "id": n_id,
                        "label": label or tail or n_id,
                        "kind": n.get("kind", "unknown"),
                        "file": n.get("source_file") or n.get("file", ""),
                        "degree": degrees.get(n_id, 0),
                    })
        return refs

    async def shared_symbols(self, min_projects: int = 2, limit: int = 50) -> list[dict]:
        """Return symbols appearing across at least min_projects repositories."""
        symbol_info: dict[str, dict] = {}

        for p_id, nodes in self._nodes_by_project.items():
            degrees = self._degrees_by_project.get(p_id, {})
            for n in nodes:
                display_name = (n.get("label") or n.get("name") or n.get("id", "").split(".")[-1]).strip()
                if not display_name:
                    continue
                key = display_name.lower()
                n_id = n.get("id", "")
                deg = degrees.get(n_id, 0)
                if key not in symbol_info:
                    symbol_info[key] = {
                        "symbol": display_name,
                        "projects": set(),
                        "total_degree": 0,
                    }
                symbol_info[key]["projects"].add(p_id)
                symbol_info[key]["total_degree"] += deg

        shared = [
            {
                "symbol": info["symbol"],
                "projects": sorted(list(info["projects"])),
                "count": len(info["projects"]),
                "total_degree": info["total_degree"],
            }
            for info in symbol_info.values()
            if len(info["projects"]) >= min_projects
        ]
        shared.sort(key=lambda s: (s["count"], s["total_degree"]), reverse=True)
        return shared[:limit]

    async def query(self, question: str, depth: int = 2, top_k: int = 10) -> list[dict]:
        """Federated query: runs hybrid search across indexed projects and combines results."""
        if not question or not question.strip():
            return []

        all_results: list[dict] = []
        for p_id, p_path in self._projects.items():
            try:
                p_res = await self.engine.hybrid_query(
                    project_path=p_path,
                    project=p_id,
                    question=question,
                    depth=depth,
                    top_k=top_k,
                )
                for r in p_res:
                    res_copy = dict(r)
                    res_copy["project"] = p_id
                    all_results.append(res_copy)
            except Exception:
                pass

        # Sort by semantic score descending
        all_results.sort(key=lambda r: r.get("semantic_score", 0.0), reverse=True)
        return all_results[:top_k]
