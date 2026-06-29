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
    AgentTaskCreatePayload, AgentTaskStatus,
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
        extractor_pipeline=None,
        extracted_store=None,
    ):
        self.registry = registry
        self.graph = graph_engine
        self.recall = recall
        self.extractor_pipeline = extractor_pipeline
        self.extracted_store = extracted_store
        self._last_update: dict[str, float] = {}  # project -> timestamp
        self._event_queue: asyncio.Queue[WsEvent] = asyncio.Queue()

    async def handle_file(self, project: str, filepath: str, user: str | None = None):
        """Route an inbox file to the correct handler."""
        path = Path(filepath)
        filename = path.name.lower()

        # Skip if file was already moved/processed
        if not path.exists():
            return

        try:
            if filename == "register.json":
                await self._handle_register(project, path, user=user)
            elif filename == "heartbeat.json":
                await self._handle_heartbeat(project, path, user=user)
            elif filename.startswith("finding-") and filename.endswith(".md"):
                await self._handle_finding(project, path, user=user)
            elif filename.startswith("decision-") and filename.endswith(".md"):
                await self._handle_decision(project, path, user=user)
            elif filename.startswith("task-") and filename.endswith(".json"):
                await self._handle_task(project, path, user=user)
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

    async def _handle_register(self, project: str, path: Path, user: str | None = None):
        payload = RegisterPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"
        if user:
            agent_id = f"{payload.agent}-{project}-{user}"

        agent = AgentInfo(
            agent_id=agent_id,
            agent_name=payload.agent,
            version=payload.version,
            project=project,
            capabilities=payload.capabilities,
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
            user=user,
        )
        await self.registry.upsert_agent(agent)
        await self.registry.upsert_project(project, payload.project_path)

        # Trigger initial graph build (which also scans knowledge sources and
        # regenerates the shared context). When graphify isn't available we
        # still scan knowledge sources and publish the shared context so the
        # agent joins the fabric — knowledge sharing doesn't need the graph.
        if self.graph.available:
            asyncio.create_task(self._build_project(project, payload.project_path))
        else:
            asyncio.create_task(
                self._scan_and_share(project, payload.project_path)
            )

        await self._emit_event("agent:online", project, {
            "agent": payload.agent,
            "capabilities": payload.capabilities,
        })

        # When a user-scoped registration occurs, emit team event
        if user:
            await self._emit_event("team:agent_joined", project, {
                "agent": payload.agent,
                "user": user,
                "capabilities": payload.capabilities,
            })

    async def _handle_heartbeat(self, project: str, path: Path, user: str | None = None):
        payload = HeartbeatPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"
        agent = await self.registry.get_agent(agent_id)
        if agent:
            agent.last_heartbeat = payload.timestamp
            agent.status = AgentStatus.ONLINE
            await self.registry.upsert_agent(agent)

    async def _handle_finding(self, project: str, path: Path, user: str | None = None):
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

        # Run knowledge extraction (regex + optional LLM) and persist edges.
        if self.extractor_pipeline is not None and self.extracted_store is not None:
            body = content.split("---", 2)[-1] if content.startswith("---") else content
            try:
                entities = await self.extractor_pipeline.run(body)
                if entities:
                    await self.extracted_store.add(project, path.name, entities)
                    await self._emit_event("extraction:completed", project, {
                        "file": path.name, "entities": len(entities),
                    })
            except Exception as exc:
                logger.warning("Extraction failed for %s: %s", path.name, exc)

        # Regenerate shared context so agents see the new finding.
        project_info = await self.registry.get_project(project)
        if project_info:
            asyncio.create_task(
                self._regenerate_shared_context(project, project_info.project_path)
            )

    async def _handle_decision(self, project: str, path: Path, user: str | None = None):
        content = path.read_text()
        frontmatter = self._parse_frontmatter(content)
        frontmatter.type = FindingType.ARCHITECTURE_DECISION

        await self._emit_event("finding:ingested", project, {
            "file": path.name,
            "type": "architecture-decision",
        })

        # Regenerate shared context so agents see the new decision record.
        project_info = await self.registry.get_project(project)
        if project_info:
            asyncio.create_task(
                self._regenerate_shared_context(project, project_info.project_path)
            )

    async def _handle_task(self, project: str, path: Path, user: str | None = None):
        payload = TaskPayload(**json.loads(path.read_text()))
        before = await self.registry.get_agent_task(payload.task_id)
        first_line = (payload.instruction.strip().splitlines() or ["Dispatched task"])[0]
        await self.registry.create_agent_task(
            AgentTaskCreatePayload(
                project=project,
                title=first_line[:80] or "Dispatched task",
                instruction=payload.instruction,
                assignee=f"{payload.target_agent}-{project}",
                priority={"low": 0, "medium": 1, "high": 2}.get(payload.priority, 1),
            ),
            task_id=payload.task_id,
            status=AgentTaskStatus.READY,
        )
        if before is None:
            record = await self.registry.get_agent_task(payload.task_id)
            await self._emit_event("task:created", project, record.model_dump())
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

        # After graph build, scan other knowledge sources and publish the
        # shared context so all agents benefit.
        await self._scan_and_share(project, project_path)

    async def _scan_and_share(self, project: str, project_path: str):
        """Ingest project knowledge sources and (re)publish the shared context.

        Scans for code-review-graph, CLAUDE.md, AGENTS.md, README, etc.,
        ingests them into the shared fabric, then regenerates
        ``.loom/SHARED_CONTEXT.md`` so every agent sees the same knowledge.
        Independent of graphify availability — knowledge sharing always runs.
        """
        try:
            from daemon.project_knowledge import ingest_all_sources
            results = await ingest_all_sources(project, project_path)
            found = sum(1 for r in results if r.get("found", True))
            ingested = sum(1 for r in results if r.get("status") == "ingested")
            logger.info(
                "Knowledge scan complete for %s: %d sources found, %d ingested",
                project, found, ingested,
            )
        except Exception as exc:
            logger.warning("Knowledge scan failed for %s: %s", project, exc)

        # Regenerate the shared agent context so all agents see the latest.
        await self._regenerate_shared_context(project, project_path)

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

        # Regenerate shared context so agents see the updated graph + findings.
        await self._regenerate_shared_context(project, project_path)

    async def _regenerate_shared_context(self, project: str, project_path: str):
        """Regenerate the shared agent context file (best-effort)."""
        try:
            from daemon.shared_context import generate_shared_context
            await generate_shared_context(
                project, project_path, self.graph, self.registry
            )
        except Exception as exc:
            logger.warning("Failed to regenerate shared context for %s: %s", project, exc)

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
