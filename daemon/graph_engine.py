"""Graphify wrapper for the Agentic OS daemon."""

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
    """Async wrapper around Graphify for build/update/query/stats."""

    def __init__(self):
        self._graphify = None
        try:
            import graphify
            self._graphify = graphify
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._graphify is not None

    async def build_project(self, project_path: str) -> BuildResult:
        """Run full Graphify build on a project."""
        project_name = Path(project_path).name
        if not self.available:
            return BuildResult(
                project=project_name,
                status="failed",
                error="Graphify not installed",
            )
        try:
            await asyncio.to_thread(
                self._run_graphify_build, project_path
            )
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
        """Run graphify CLI build (blocking)."""
        try:
            subprocess.run(
                ["graphify", project_path],
                capture_output=True,
                timeout=300,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            # Preserve graphify's stderr so failures are debuggable.
            raise RuntimeError(_decode_subprocess_error(e)) from e

    async def update_project(self, project_path: str, files: list[str]) -> BuildResult:
        """Incremental update for changed files."""
        project_name = Path(project_path).name
        if not self.available:
            return BuildResult(
                project=project_name,
                status="failed",
                error="Graphify not installed",
            )
        try:
            await asyncio.to_thread(
                self._run_graphify_update, project_path
            )
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

    def _run_graphify_update(self, project_path: str):
        """Run graphify --update (blocking)."""
        try:
            subprocess.run(
                ["graphify", project_path, "--update"],
                capture_output=True,
                timeout=300,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(_decode_subprocess_error(e)) from e

    async def get_stats(self, project_path: str) -> GraphStats:
        """Read graph stats from graphify-out/graph.json."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return GraphStats(nodes=0, edges=0, communities=0)

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        communities = data.get("communities", {})

        return GraphStats(
            nodes=len(nodes),
            edges=len(edges),
            communities=len(communities),
        )

    @staticmethod
    def _read_graph_json(path: Path) -> dict:
        with open(path) as f:
            return json.load(f)

    async def get_topology(self, project_path: str) -> dict:
        """Return full graph topology (nodes + edges) for visualization."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return {"nodes": [], "edges": []}

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

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

    async def get_communities(self, project_path: str) -> list[dict]:
        """Return community list with sizes."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return []

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        communities = data.get("communities", {})
        result = []
        for cid, cdata in communities.items():
            result.append({
                "id": cid,
                "name": cdata.get("name", f"Community {cid}"),
                "size": len(cdata.get("members", [])),
            })
        return sorted(result, key=lambda c: c["size"], reverse=True)

    async def get_flows(self, project_path: str) -> list[dict]:
        """Return execution flows."""
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

    async def query(self, project_path: str, question: str) -> QueryResult:
        """Query the project graph."""
        if not self.available:
            return QueryResult(question=question, results=[])

        try:
            result = await asyncio.to_thread(
                self._run_graphify_query, project_path, question
            )
            return QueryResult(question=question, results=result)
        except Exception:
            return QueryResult(question=question, results=[])

    def _run_graphify_query(self, project_path: str, question: str) -> list[dict]:
        import subprocess
        result = subprocess.run(
            ["graphify", "query", question],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_path,
        )
        lines = result.stdout.strip().split("\n")
        return [{"text": line} for line in lines if line.strip()]
