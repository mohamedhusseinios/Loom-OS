"""Event router — processes inbox files and dispatches actions."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from daemon.registry import AgentRegistry
from daemon.graph_engine import GraphEngine
from daemon.models import (
    RegisterPayload, HeartbeatPayload, FindingFrontmatter,
    AgentInfo, AgentStatus, FindingType, WsEvent, TaskPayload,
)

if TYPE_CHECKING:
    from daemon.recall import RecallEngine

logger = logging.getLogger(__name__)

# Rate limiting: min seconds between graph updates per project
MIN_UPDATE_INTERVAL = 30


class Router:
    """Processes inbox events and dispatches to registry + graph engine."""

    def __init__(
        self,
        registry: AgentRegistry,
        graph_engine: GraphEngine,
        recall: RecallEngine | None = None,
    ):
        self.registry = registry
        self.graph = graph_engine
        self.recall = recall
        self._last_update: dict[str, float] = {}  # project -> timestamp
        self._event_queue: asyncio.Queue[WsEvent] = asyncio.Queue()

    async def handle_file(self, project: str, filepath: str):
        """Route an inbox file to the correct handler."""
        path = Path(filepath)
        filename = path.name.lower()

        # Skip if file was already moved/processed
        if not path.exists():
            return

        try:
            if filename == "register.json":
                await self._handle_register(project, path)
            elif filename == "heartbeat.json":
                await self._handle_heartbeat(project, path)
            elif filename.startswith("finding-") and filename.endswith(".md"):
                await self._handle_finding(project, path)
            elif filename.startswith("decision-") and filename.endswith(".md"):
                await self._handle_decision(project, path)
            elif filename.startswith("task-") and filename.endswith(".json"):
                await self._handle_task(project, path)
            else:
                logger.debug(f"Ignoring unknown file: {filename}")
                return

            # Move to processed (ignore if already moved)
            try:
                processed_dir = path.parent / ".processed"
                processed_dir.mkdir(exist_ok=True)
                path.rename(processed_dir / path.name)
            except FileNotFoundError:
                pass  # file already moved by previous event

        except Exception as e:
            logger.error(f"Error handling {filepath}: {e}")
            await self._emit_error(project, filepath, str(e))

    async def _handle_register(self, project: str, path: Path):
        payload = RegisterPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"

        agent = AgentInfo(
            agent_id=agent_id,
            agent_name=payload.agent,
            version=payload.version,
            project=project,
            capabilities=payload.capabilities,
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )
        await self.registry.upsert_agent(agent)
        await self.registry.upsert_project(project, payload.project_path)

        # Trigger initial graph build
        if self.graph.available:
            asyncio.create_task(self._build_project(project, payload.project_path))

        await self._emit_event("agent:online", project, {
            "agent": payload.agent,
            "capabilities": payload.capabilities,
        })

    async def _handle_heartbeat(self, project: str, path: Path):
        payload = HeartbeatPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"
        agent = await self.registry.get_agent(agent_id)
        if agent:
            agent.last_heartbeat = payload.timestamp
            agent.status = AgentStatus.ONLINE
            await self.registry.upsert_agent(agent)

    async def _handle_finding(self, project: str, path: Path):
        content = path.read_text()
        frontmatter = self._parse_frontmatter(content)

        # If finding references code files, queue incremental update
        if frontmatter.files and self._can_update(project):
            project_info = await self.registry.get_project(project)
            if project_info:
                asyncio.create_task(
                    self._update_project(project, project_info.project_path, frontmatter)
                )

        await self._emit_event("finding:ingested", project, {
            "file": path.name,
            "type": frontmatter.type.value,
        })

    async def _handle_decision(self, project: str, path: Path):
        content = path.read_text()
        frontmatter = self._parse_frontmatter(content)
        frontmatter.type = FindingType.ARCHITECTURE_DECISION

        await self._emit_event("finding:ingested", project, {
            "file": path.name,
            "type": "architecture-decision",
        })

    async def _handle_task(self, project: str, path: Path):
        payload = TaskPayload(**json.loads(path.read_text()))
        # Idempotent: if the API already persisted this task, don't
        # re-insert or re-broadcast. create_task returns False on collision.
        created = await self.registry.create_task(
            payload.task_id, project, payload.target_agent,
            payload.instruction, payload.priority,
        )
        if created:
            await self._emit_event("agent:dispatched", project, {
                "task_id": payload.task_id,
                "target_agent": payload.target_agent,
                "instruction": payload.instruction,
            })

    def _parse_frontmatter(self, content: str) -> FindingFrontmatter:
        """Parse YAML frontmatter from markdown."""
        import yaml
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                data = yaml.safe_load(parts[1])
                return FindingFrontmatter(**data)
        return FindingFrontmatter(agent="unknown", project="unknown")

    def _can_update(self, project: str) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        last = self._last_update.get(project, 0)
        if now - last >= MIN_UPDATE_INTERVAL:
            self._last_update[project] = now
            return True
        return False

    async def _build_project(self, project: str, project_path: str):
        result = await self.graph.build_project(project_path)
        # Persist stats so the dashboard's project list reflects the build.
        # Communities aren't in BuildResult; read them from the graph output.
        communities = 0
        if result.status == "completed":
            stats = await self.graph.get_stats(project_path)
            communities = stats.communities
            await self.registry.update_graph_stats(
                project, result.nodes, result.edges, communities
            )
        await self._emit_event("graph:updated", project, {
            "nodes_added": result.nodes,
            "edges_added": result.edges,
            "communities": communities,
            "status": result.status,
            "error": result.error,
        })

    async def _update_project(self, project: str, project_path: str, finding: FindingFrontmatter):
        result = await self.graph.update_project(project_path, finding.files)
        communities = 0
        if result.status == "completed":
            stats = await self.graph.get_stats(project_path)
            communities = stats.communities
            await self.registry.update_graph_stats(
                project, result.nodes, result.edges, communities
            )
        await self._emit_event("graph:updated", project, {
            "nodes_added": result.nodes,
            "edges_added": result.edges,
            "communities": communities,
            "status": result.status,
            "error": result.error,
            "agent": finding.agent,
        })

    async def _emit_event(self, event: str, project: str, data: dict):
        ws_event = WsEvent(event=event, project=project, data=data)
        await self._event_queue.put(ws_event)

    async def _emit_error(self, project: str, filepath: str, message: str):
        await self._emit_event("error", project, {
            "file": filepath,
            "message": message,
        })

    @property
    def events(self) -> asyncio.Queue[WsEvent]:
        return self._event_queue
