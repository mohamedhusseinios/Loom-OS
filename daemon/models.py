"""Pydantic models for the Agentic OS daemon."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    WORKING = "working"


class FindingType(str, Enum):
    CODE_ANALYSIS = "code-analysis"
    ARCHITECTURE_DECISION = "architecture-decision"
    BUG_REPORT = "bug-report"
    GENERAL = "general"


# --- Inbox File Schemas ---

class RegisterPayload(BaseModel):
    agent: str
    version: str
    project: str
    project_path: str
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatPayload(BaseModel):
    agent: str
    project: str
    status: str = ""
    timestamp: datetime


class FindingFrontmatter(BaseModel):
    agent: str
    project: str
    type: FindingType = FindingType.GENERAL
    files: list[str] = Field(default_factory=list)
    timestamp: Optional[datetime] = None


# --- Registry Models ---

class AgentInfo(BaseModel):
    agent_id: str
    agent_name: str
    version: str
    project: str
    capabilities: list[str]
    status: AgentStatus = AgentStatus.ONLINE
    last_heartbeat: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectInfo(BaseModel):
    project_id: str
    project_name: str
    project_path: str
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
    last_graph_update: Optional[datetime] = None
    active_agents: int = 0
    total_findings: int = 0


# --- API Response Schemas ---

class GraphStats(BaseModel):
    nodes: int
    edges: int
    communities: int
    top_communities: list[dict] = Field(default_factory=list)
    god_nodes: list[dict] = Field(default_factory=list)
    last_updated: Optional[datetime] = None


class ProjectSummary(BaseModel):
    project: ProjectInfo
    graph: Optional[GraphStats] = None
    agents: list[AgentInfo] = Field(default_factory=list)


class ActivityEvent(BaseModel):
    timestamp: datetime
    event_type: str
    project: str
    agent: Optional[str] = None
    details: dict = Field(default_factory=dict)


class QueryResult(BaseModel):
    question: str
    results: list[dict]
    communities: list[str] = Field(default_factory=list)


class BuildResult(BaseModel):
    project: str
    status: str  # "started" | "completed" | "failed"
    nodes: int = 0
    edges: int = 0
    error: Optional[str] = None

# --- Project CRUD Schemas ---

class ProjectCreatePayload(BaseModel):
    name: str
    path: str

class ProjectDeleteResult(BaseModel):
    deleted: bool

class DiscoverResult(BaseModel):
    directories: list[dict] = Field(default_factory=list)
    parent: Optional[str] = None

# --- WebSocket Events ---

class WsEvent(BaseModel):
    event: str
    project: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
