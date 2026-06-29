# API Reference

All endpoints on `http://localhost:8472`. CORS allows only `http://localhost:3000`.

## REST Endpoints

### Health & Discovery

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check (daemon status, graphify availability, watcher running) |
| `GET` | `/api/discover?path=` | Browse filesystem directories for project discovery |

### Projects

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects` | List all tracked projects with node/edge/community/agent counts |
| `POST` | `/api/projects` | Create a tracked project (`{name, path}`) → 201 | 409 if exists |
| `GET` | `/api/projects/:id` | Project detail with graph stats and agent list |
| `DELETE` | `/api/projects/:id` | Remove a project from tracking |

### Graph

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/graph` | Graph stats only (nodes, edges, communities) |
| `GET` | `/api/projects/:id/graph/topology` | Full node/edge topology for visualization |
| `GET` | `/api/projects/:id/graph/communities` | Community list with sizes |
| `GET` | `/api/projects/:id/graph/flows` | Execution flows, ranked by criticality |
| `GET` | `/api/projects/:id/extracted-edges` | LLM-extracted (non-AST) edges for graph overlay |
| `GET` | `/api/projects/:id/query?q=` | Natural language query of the knowledge graph |
| `POST` | `/api/projects/:id/rebuild` | Force a full graph rebuild |

### Search

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/search?q=&mode=text` | Text + vector search over findings (default) |
| `GET` | `/api/projects/:id/search?q=&mode=hybrid` | Graph + vector + relational search (vector-seeded BFS over AST + extracted edges) |

### Agents

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/agents` | List agents with status and capabilities |

### Tasks & Dispatch

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/:id/dispatch` | Dispatch a task to an agent (`{target_agent, instruction, priority?}`) |
| `GET` | `/api/projects/:id/dispatches` | List recent task dispatches (newest first, max 50) |
| `GET` | `/api/projects/:id/tasks` | List all tasks for a project (supports status filter) |
| `POST` | `/api/projects/:id/tasks` | Create a task (`{title, assignee, body?, parents?, priority?}`) |
| `PATCH` | `/api/projects/:id/tasks/:taskId` | Update task status or metadata |
| `GET` | `/api/projects/:id/tasks/:taskId` | Get task detail |

### Context & Knowledge

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/context` | Auto-generated shared context (graph stats, findings, agents) |
| `GET` | `/api/projects/:id/knowledge` | List knowledge sources discovered in the project |
| `POST` | `/api/projects/:id/knowledge/scan` | Scan and ingest all knowledge sources |

### Task Board (Kanban)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/tasks?status=` | List tasks (optional status filter) |
| `POST` | `/api/projects/:id/tasks` | Create a task (`{title, instruction, assignee?, priority?}`) |
| `PATCH` | `/api/projects/:id/tasks/:taskId` | Update task status/assignee/result |
| `POST` | `/api/projects/:id/tasks/:taskId/progress` | Record a progress line |
| `GET` | `/api/projects/:id/tasks/:taskId/progress` | Get progress transcript |
| `POST` | `/api/projects/:id/tasks/:taskId/worker/start` | Manually start worker for a task |
| `POST` | `/api/projects/:id/tasks/:taskId/worker/stop` | Stop a live worker |
| `GET` | `/api/projects/:id/workers` | List task ids with live worker processes |
| `GET` | `/api/projects/:id/tasks/:taskId/diff` | Git diff for a task's worktree branch |
| `POST` | `/api/projects/:id/tasks/:taskId/merge` | Merge a task's branch into a target |
| `GET` | `/api/projects/:id/branches` | List local + remote branches for merge target |

### Agents

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/:id/register-agent` | Register a coding agent (dual-write: inbox + immediate) |
| `DELETE` | `/api/projects/:id/agents/:agentId` | Remove an agent from a project |
| `GET` | `/api/agents/known` | Known agent types + which are installed on this machine |
| `GET` | `/api/agents/runnable` | Agents the daemon can spawn as workers |

### Evaluation

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/:id/eval` | Run an evaluation against agent output |
| `GET` | `/api/projects/:id/eval` | Return evaluation results |
| `GET` | `/api/projects/:id/eval/pass-rate` | Pass/warn/fail rates |

### Patterns

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/patterns?project=&status=` | List evolved patterns |
| `GET` | `/api/patterns/top?limit=` | Highest-confidence patterns |
| `GET` | `/api/patterns/cross-project` | Patterns seen across multiple projects |
| `POST` | `/api/projects/:id/patterns/observe` | Record a pattern observation |
| `PATCH` | `/api/patterns/:patternId/deprecate` | Mark a pattern as deprecated |

### Audit, Temporal, Ingestion

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/audit?agent_id=&action=&limit=` | Audit log events |
| `GET` | `/api/projects/:id/audit/summary` | Daily audit summary |
| `POST` | `/api/projects/:id/facts` | Record a temporal fact |
| `GET` | `/api/projects/:id/facts?active_only=` | List temporal facts |
| `GET` | `/api/projects/:id/facts/timeline` | Facts in chronological order |
| `PATCH` | `/api/facts/:factId/expire` | Expire a temporal fact |
| `POST` | `/api/projects/:id/ingest` | Ingest a document into the knowledge base |
| `POST` | `/api/projects/:id/ingest/directory` | Ingest all files in a directory |

### Debugging

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/snapshots?agent_id=` | Agent state snapshots for time-travel debugging |
| `GET` | `/api/traces?project=&agent_id=&limit=` | Recent agent execution traces |

## WebSocket (`/ws`)

Single endpoint. Server pushes JSON events to all connected clients.

### Event Types

| Event | Payload | When |
|-------|---------|------|
| `agent:online` | `{agent, capabilities}` | Agent registers |
| `agent:offline` | `{agent_id}` | Agent removed via dashboard |
| `agent:dispatched` | `{task_id, target_agent, instruction}` | Task dispatched to agent |
| `graph:updated` | `{nodes_added, edges_added, communities, status, error?}` | Build/update completes |
| `finding:ingested` | `{file, type}` | Finding/decision processed |
| `extraction:completed` | `{file, entities}` | LLM/regex extraction finishes on a finding |
| `project:created` | `{project_id, project_name}` | Project added |
| `project:deleted` | `{project_id}` | Project removed |
| `task:created` | `{task_id, project_id, assignee, status}` | Task created |
| `task:updated` | `{task_id, project_id, status}` | Task status changed |
| `task:completed` | `{task_id, project_id, summary}` | Worker finishes task |
| `task:failed` | `{task_id, error}` | Worker or build fails |
| `task:progress` | `{id, seq, kind, message}` | Worker progress update |
| `worker:started` | `{id}` | Worker process spawned |
| `worker:exited` | `{id}` | Worker process stopped |
| `knowledge:scanned` | `{sources_found, sources_ingested}` | Knowledge source scan completes |
| `error` | `{file, message}` | Processing failure |

## Error Responses

| HTTP Status | Scenario |
|-------------|----------|
| 400 | Missing query param, invalid path, malformed input |
| 404 | Project not found |
| 409 | Duplicate project name |

All errors return `{"detail": "<message>"}`.
