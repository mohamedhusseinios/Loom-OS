"""Graphify wrapper for the Loom daemon.

Uses ``graphify update`` for code-only graph builds (AST extraction, no LLM).
Zero external dependencies — no API keys, no local LLM servers required.
"""

import asyncio
import json
import subprocess
from pathlib import Path
from daemon.models import BuildResult, GraphStats, QueryResult


def _decode_subprocess_error(e: subprocess.CalledProcessError) -> str:
    """Extract a useful message from a failed graphify subprocess call."""
    if e.stderr:
        msg = e.stderr.decode(errors="replace").strip()
        if msg:
            return msg
    return str(e)


class GraphEngine:
    """Async wrapper around Graphify for build/update/query/stats.

    The initial build creates a stub ``graph.json`` (if one doesn't exist)
    and then runs ``graphify update`` which re-extracts *code files only*
    via AST parsing — no LLM, no API key, no local server required.

    Incremental updates (when agents drop findings) go through the same
    ``update`` path for speed.
    """

    def __init__(self):
        self._graphify = None
        try:
            import graphify  # noqa: F401 — only used as a sentinel
            self._graphify = True
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._graphify is not None

    # ----------------------------------------------------------------
    # Build / update
    # ----------------------------------------------------------------

    async def build_project(self, project_path: str) -> BuildResult:
        """Run a code-only graph build (AST extraction, no LLM)."""
        project_name = Path(project_path).name
        if not self.available:
            return BuildResult(
                project=project_name,
                status="failed",
                error="Graphify not installed",
            )
        try:
            await asyncio.to_thread(self._run_graphify_build, project_path)
            stats = await self.get_stats(project_path)
            return BuildResult(
                project=project_name,
                status="completed",
                nodes=stats.nodes,
                edges=stats.edges,
            )
        except Exception as e:
            return BuildResult(
                project=project_name,
                status="failed",
                error=str(e),
            )

    def _run_graphify_build(self, project_path: str):
        """Run ``graphify update`` (code-only, no LLM).

        If no ``graph.json`` exists yet, create a minimal stub first —
        ``graphify update`` needs an existing graph to update.
        """
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            graph_path.write_text('{"nodes":[],"links":[]}')

        try:
            # NB: the subcommand comes first — ``graphify update <path>``.
            # The transposed form ``graphify <path> --update`` makes graphify
            # run its default full extraction (docs/papers/images), which needs
            # an LLM API key, exits non-zero, and leaves graph.json as the empty
            # stub — so the dashboard reports "build complete" over an empty graph.
            subprocess.run(
                ["graphify", "update", project_path],
                capture_output=True,
                timeout=300,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(_decode_subprocess_error(e)) from e

    async def update_project(self, project_path: str, files: list[str]) -> BuildResult:
        """Incremental update (code-only) — same as build but preserves existing graph."""
        return await self.build_project(project_path)

    # ----------------------------------------------------------------
    # Graph reading
    # ----------------------------------------------------------------

    @staticmethod
    def _read_graph_json(path: Path) -> dict:
        with open(path) as f:
            return json.load(f)

    async def get_stats(self, project_path: str) -> GraphStats:
        """Read node / edge / community counts from the graph JSON."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return GraphStats(nodes=0, edges=0, communities=0)

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        nodes = data.get("nodes", [])
        links = data.get("links", data.get("edges", []))

        communities: set[int] = set()
        for n in nodes:
            cid = n.get("community")
            if cid is not None:
                communities.add(cid)

        return GraphStats(
            nodes=len(nodes),
            edges=len(links),
            communities=len(communities),
        )

    async def get_topology(self, project_path: str) -> dict:
        """Return full graph topology (nodes + edges) for Cytoscape visualization."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return {"nodes": [], "edges": []}

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        raw_nodes = data.get("nodes", [])
        raw_links = data.get("links", data.get("edges", []))

        result_nodes = []
        for n in raw_nodes:
            result_nodes.append({
                "id": n.get("id", ""),
                "label": n.get("label", n.get("id", "")),
                "kind": n.get("file_type", n.get("kind", "Unknown")),
                "community": n.get("community", 0),
                "file": n.get("source_file", n.get("file", "")),
            })

        result_edges = []
        for lnk in raw_links:
            result_edges.append({
                "source": lnk.get("source", ""),
                "target": lnk.get("target", ""),
                "kind": lnk.get("relation", lnk.get("kind", "references")),
            })

        return {"nodes": result_nodes, "edges": result_edges}

    async def get_communities(self, project_path: str) -> list[dict]:
        """Return community list with sizes.

        The code-only graph stores communities as integer IDs on nodes
        (no metadata block).  We synthesise a name from the most common
        parent directory of the community's files.
        """
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return []

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        nodes = data.get("nodes", [])

        # Group nodes by community ID
        comm_files: dict[int, list[str]] = {}
        for n in nodes:
            cid = n.get("community")
            if cid is None:
                continue
            fpath = n.get("source_file", "")
            if fpath:
                comm_files.setdefault(cid, []).append(fpath)

        result = []
        for cid, files in comm_files.items():
            # Synthesise a name from the most common top-level directory
            tops: dict[str, int] = {}
            for fp in files:
                top = fp.split("/")[0] if "/" in fp else fp
                tops[top] = tops.get(top, 0) + 1
            best = max(tops, key=lambda k: tops[k]) if tops else f"Community {cid}"
            result.append({
                "id": str(cid),
                "name": best,
                "size": len(files),
            })

        return sorted(result, key=lambda c: c["size"], reverse=True)

    async def get_flows(self, project_path: str) -> list[dict]:
        """Return execution flows (empty for code-only graphs)."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return []

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        flows = data.get("flows", [])
        result = []
        for f in flows:
            result.append({
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "criticality": f.get("criticality", 0),
                "node_ids": [s.get("node_id", "") for s in f.get("steps", [])],
            })
        return sorted(result, key=lambda f: f["criticality"], reverse=True)

    # ----------------------------------------------------------------
    # Query
    # ----------------------------------------------------------------

    async def query(self, project_path: str, question: str) -> QueryResult:
        """Query the project graph via ``graphify query``."""
        if not self.available:
            return QueryResult(question=question, results=[])

        try:
            result = await asyncio.to_thread(
                self._run_graphify_query, project_path, question
            )
            return QueryResult(question=question, results=result)
        except Exception:
            return QueryResult(question=question, results=[])

    @staticmethod
    def _run_graphify_query(project_path: str, question: str) -> list[dict]:
        result = subprocess.run(
            ["graphify", "query", question],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_path,
        )
        lines = result.stdout.strip().split("\n")
        return [{"text": line} for line in lines if line.strip()]
