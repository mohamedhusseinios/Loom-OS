"""Graphify wrapper for the Agentic OS daemon."""

import asyncio
import json
from pathlib import Path
from daemon.models import BuildResult, GraphStats, QueryResult


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
        import subprocess
        subprocess.run(
            ["graphify", project_path],
            capture_output=True,
            timeout=300,
            check=True,
        )

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
        import subprocess
        subprocess.run(
            ["graphify", project_path, "--update"],
            capture_output=True,
            timeout=300,
            check=True,
        )

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
