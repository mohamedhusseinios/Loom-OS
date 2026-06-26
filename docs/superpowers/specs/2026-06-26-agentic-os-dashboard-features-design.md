# Loom Dashboard Features — Design Spec

**Date:** 2026-06-26
**Status:** Design approved — ready for implementation planning
**Project:** Loom (standalone)
**Parent Spec:** [2026-06-25-loom-design.md](./2026-06-25-loom-design.md)

## Overview

Three new dashboard features that extend the Loom control plane: manual project management (no longer agent-discovery-only), an interactive visual graph explorer powered by Cytoscape.js, and a full agent management page with wiring diagrams and task dispatch.

All three features follow the existing **API-First** architecture: daemon endpoints serve structured data, dashboard renders it. No new transport mechanisms — the existing filesystem inbox protocol is extended for agent dispatch.

## Feature 1: Project CRUD

### Current State
Projects only appear when an agent writes `register.json` to `~/.loom/inbox/<project>/`. The dashboard has no way to create or browse projects directly.

### Design

**"Add Project" flow:**
1. User clicks "+ Add Project" in sidebar or the empty-state card on the projects page
2. Modal opens with two tabs: **Browse Disk** and **Manual Entry**
3. Browse Disk: directory picker starting from `~/` — user navigates to a project directory. Daemon provides `GET /api/discover?path=` that returns subdirectories.
4. Manual Entry: user types a project name and absolute path
5. On submit: `POST /api/projects {name, path}` → daemon creates SQLite row, returns project

**Sidebar enhancement:**
- Project list in sidebar shows all tracked projects with live agent count badges
- Active project highlighted based on current route
- "+ Add Project" link at bottom of project list

**Project deletion:**
- `DELETE /api/projects/:id` removes project from tracking (does NOT delete files on disk)
- Confirmation dialog before deletion

### New API Endpoints

| Method | Path | Request Body | Response |
|--------|------|-------------|----------|
| POST | `/api/projects` | `{name: string, path: string}` | `ProjectInfo` |
| DELETE | `/api/projects/:id` | — | `{deleted: true}` |
| GET | `/api/discover?path=` | — | `{directories: [{name, path, has_git}]}` |

### Key Decisions
- **No auto-build on create** — graph build only happens when an agent registers or user clicks "Rebuild." Keeps project creation fast and predictable.
- **Browse is read-only** — daemon only lists directories, never modifies the filesystem outside `~/.loom/`.
- **Path validation** — daemon verifies the path exists and is a directory before creating the project.

### Components
- **AddProjectModal** — two-tab dialog (Browse / Manual), path validation, loading state
- **Sidebar** (modified) — project list with badges, "+ Add Project" link
- **ProjectCard** (modified) — existing card, no changes needed

---

## Feature 2: Graph Visual Explorer

### Current State
`/projects/[id]/graph` is a text-only query interface. User types a question, gets text results. No visual representation of the graph.

### Design

**Page layout (replaces current graph page):**
- **Left sidebar (220px):** Search bar, community filter chips, flow selector, view toggles
- **Center canvas:** Cytoscape.js force-directed graph (cose-bilkent layout)
- **Node detail panel:** Floating card (bottom-right) showing selected node info
- **Zoom controls:** Top-right overlay (+, −, fit)

**Interactions:**
- **Click node** → NodeDetail panel shows: name, kind (Function/Class/File), file path, community, in/out degree, "Show Callers" / "Show Callees" actions
- **Click community chip** → toggles visibility of that community's nodes
- **Click flow** → highlights the call path through the graph (dims everything else)
- **Search** → types node name, focuses and highlights matching nodes
- **Zoom/pan** — standard Cytoscape.js gestures (scroll to zoom, drag to pan)
- **Live updates** — WebSocket `graph:updated` triggers smooth re-render with transition animation

**Data sources:**
- `GET /api/projects/:id/graph/topology` — full nodes + edges as lightweight JSON
- `GET /api/projects/:id/graph/communities` — community list with member counts
- `GET /api/projects/:id/graph/flows` — execution flows (call paths)
- Existing `GET /api/projects/:id/query?q=` — NL query (kept, results highlight on graph)

### New API Endpoints

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/projects/:id/graph/topology` | `{nodes: [{id, label, kind, community, file}], edges: [{source, target, kind}]}` |
| GET | `/api/projects/:id/graph/communities` | `{communities: [{id, name, size, color}]}` |
| GET | `/api/projects/:id/graph/flows` | `{flows: [{id, name, criticality, node_ids}]}` |

### Graph Data Format (Topology)

```json
{
  "nodes": [
    {"id": "daemon.router.Router", "label": "Router", "kind": "Class", "community": 3, "file": "daemon/router.py"}
  ],
  "edges": [
    {"source": "daemon.api.list_projects", "target": "daemon.registry.AgentRegistry.list_projects", "kind": "calls"}
  ]
}
```

**Size handling:** For graphs > 500 nodes, the endpoint returns community-level aggregation by default. Full topology available with `?full=true` (paginated or streamed).

### Components
- **GraphCanvas** — Cytoscape.js instance, receives elements as prop, emits selection events
- **GraphControls** — left sidebar: search, communities, flows, toggles
- **NodeDetail** — floating panel on node selection
- **useGraphData** — hook: fetches topology/communities/flows, transforms to Cytoscape elements, re-fetches on WS events

### Dependencies
- `cytoscape` npm package (core)
- `cytoscape-cose-bilkent` (layout)
- No additional Python dependencies (daemon reads existing `graphify-out/graph.json`)

---

## Feature 3: Agent Management & Wiring

### Current State
Agents appear as simple badges on the project detail page (name + status dot + capabilities). No dedicated management page, no relationship visualization, no task dispatch.

### Design

**Page: `/projects/[id]/agents`**

**Agent Cards:**
- Rich card per agent: avatar (initials), name, version, status dot (online/working/offline), registered time
- Capability tags (colored chips)
- Finding count + "last heartbeat" timestamp
- Expand to show contribution history (findings submitted)

**Agent Wiring Diagram:**
- Horizontal chain showing agent relationships
- Nodes: agent avatars + task nodes
- Edges: findings contributed (solid line) and tasks dispatched (dashed/directed arrow)
- Built from agent registry data + dispatch history
- Shows the flow: Agent A → finding → consumed by Agent B → Agent B dispatched task → Agent C

**Task Dispatch:**
- "Dispatch Task" button opens modal
- Form: select target agent (dropdown from registered agents), instruction (textarea), priority (low/medium/high)
- On submit: `POST /api/projects/:id/dispatch` → daemon writes `task-<uuid>.json` to inbox
- Dispatch history table: type, instruction, target, status (pending/completed/failed), timestamp
- Updates via WebSocket (`agent:dispatched`, `task:completed`)

### Dispatch Protocol

New inbox file type: `task-<uuid>.json`

```json
{
  "type": "task",
  "task_id": "uuid",
  "target_agent": "claude-code",
  "instruction": "Review the auth module for security issues",
  "priority": "medium",
  "dispatched_by": "dashboard",
  "timestamp": "2026-06-26T10:00:00Z"
}
```

**Lifecycle:**
1. Dashboard POST → daemon writes `task-<uuid>.json` to `~/.loom/inbox/<project>/`
2. Watcher detects → Router processes → emits `agent:dispatched` WS event
3. Target agent reads task from inbox (implementation: agent polling or watchdog on agent side)
4. Agent writes finding-*.md or result back → Router ingests
5. WS `finding:ingested` closes the loop

### New API Endpoints

| Method | Path | Request Body | Response |
|--------|------|-------------|----------|
| GET | `/api/projects/:id/agents` | — | `{agents: AgentInfo[]}` (extended with finding_count) |
| POST | `/api/projects/:id/dispatch` | `{target_agent, instruction, priority}` | `{task_id, status: "dispatched"}` |
| GET | `/api/projects/:id/dispatches` | — | `{dispatches: [{task_id, target_agent, instruction, status, timestamp}]}` |

### New Daemon Models

```python
class TaskPayload(BaseModel):
    type: str = "task"
    task_id: str
    target_agent: str
    instruction: str
    priority: str = "medium"  # low | medium | high
    dispatched_by: str = "dashboard"
    timestamp: datetime
```

### Components
- **AgentCard** — rich card with expandable contribution history
- **AgentWiring** — horizontal chain diagram (agents → findings → tasks)
- **DispatchModal** — form: target selector, instruction, priority
- **DispatchHistory** — table of past dispatches with status badges
- **useAgents** — hook: fetches agent list + dispatches, subscribes to WS events

---

## WebSocket Events (New)

| Event | Payload | Feature |
|-------|---------|---------|
| `project:created` | `{project_id, project_name}` | Project CRUD |
| `project:deleted` | `{project_id}` | Project CRUD |
| `agent:dispatched` | `{task_id, target_agent, instruction}` | Agent Mgmt |
| `task:completed` | `{task_id, agent, result}` | Agent Mgmt |
| `graph:topology-updated` | `{project, nodes_added, edges_added}` | Graph Explorer |

Existing events (`graph:updated`, `agent:online`, `agent:offline`, `finding:ingested`) continue to work.

---

## File Changes Summary

### Daemon (Python)
| File | Change |
|------|--------|
| `daemon/models.py` | Add `TaskPayload`, `ProjectCreatePayload`, `DiscoverResult`, `GraphTopology`, `DispatchResult` models |
| `daemon/api.py` | Add 7 new endpoints, modify list_agents to include finding_count |
| `daemon/registry.py` | Add `delete_project`, `create_project`, `list_dispatches` methods; add `tasks` table |
| `daemon/router.py` | Add `_handle_task` handler for task-*.json files; emit new WS events |
| `daemon/graph_engine.py` | Add `get_topology`, `get_communities`, `get_flows` methods reading from graph.json |
| `daemon/main.py` | No changes (endpoints auto-register via FastAPI) |

### Dashboard (Next.js)
| File | Change |
|------|--------|
| `components/sidebar.tsx` | Add project list with badges, "+ Add Project" link |
| `components/add-project-modal.tsx` | **New** — browse/manual entry dialog |
| `app/page.tsx` | Add "Add Project" card to project grid |
| `app/projects/[id]/agents/page.tsx` | **New** — agent management page |
| `components/agent-card.tsx` | **New** — rich agent card |
| `components/agent-wiring.tsx` | **New** — horizontal chain diagram |
| `components/dispatch-modal.tsx` | **New** — task dispatch form |
| `components/dispatch-history.tsx` | **New** — dispatch history table |
| `app/projects/[id]/graph/page.tsx` | **Rewrite** — Cytoscape.js explorer |
| `components/graph-canvas.tsx` | **New** — Cytoscape.js wrapper |
| `components/graph-controls.tsx` | **New** — left sidebar controls |
| `components/node-detail.tsx` | **New** — floating node info panel |
| `components/graph-stats.tsx` | Keep (used on project detail page) |
| `lib/api.ts` | Add new API functions |
| `package.json` | Add `cytoscape`, `cytoscape-cose-bilkent` |

---

## Testing Strategy

### Daemon Tests
- `POST /api/projects` — creates project, validates path existence
- `DELETE /api/projects/:id` — removes project, returns 404 for missing
- `GET /api/discover?path=` — returns subdirectories, handles invalid paths
- `GET /api/projects/:id/graph/topology` — returns nodes/edges from graph.json
- `POST /api/projects/:id/dispatch` — writes task file, returns task_id
- Router: `_handle_task` processes task-*.json correctly
- Registry: task table CRUD

### Dashboard Tests
- ProjectCard renders with/without agents
- AddProjectModal validates path, submits correctly
- GraphCanvas renders Cytoscape instance with mock data
- AgentWiring renders chain from agent+dispatch data
- DispatchModal submits and shows loading state

---

## Out of Scope (This Feature Set)

- Real-time agent response to dispatched tasks (agents must implement polling)
- Agent-to-agent direct messaging (tasks go through inbox, not direct)
- Graph editing (graph is read-only in dashboard)
- Authentication/authorization for dashboard
- Multi-machine agent federation

---

## Dependencies Between Features

```
Project CRUD ──► Graph Explorer (needs project to exist)
Project CRUD ──► Agent Management (needs project to have agents)
Agent Management ──► Agent Wiring (uses agents + dispatches)
```

Implementation order should be: **Project CRUD first**, then Graph Explorer + Agent Management in parallel (they're independent of each other once projects exist).
