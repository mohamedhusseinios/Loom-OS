const BASE_URL = "http://localhost:8472";

export interface ProjectSummary {
  project: {
    project_id: string;
    project_name: string;
    project_path: string;
    node_count: number;
    edge_count: number;
    community_count: number;
    last_graph_update: string | null;
    active_agents: number;
    total_findings: number;
  };
  graph: {
    nodes: number;
    edges: number;
    communities: number;
  } | null;
  agents: AgentInfo[];
}

export interface AgentInfo {
  agent_id: string;
  agent_name: string;
  version: string;
  project: string;
  capabilities: string[];
  structured_capabilities: {
    name: string;
    description: string;
    tools: string[];
    models: string[];
    status: string;
  }[];
  status: "online" | "offline" | "working";
  last_heartbeat: string | null;
  registered_at: string;
}

export interface GraphStats {
  nodes: number;
  edges: number;
  communities: number;
}

export interface QueryResult {
  question: string;
  results: { text: string }[];
  communities: string[];
}

async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function listProjects(): Promise<{ projects: ProjectSummary["project"][] }> {
  return fetchApi("/api/projects");
}

export async function getProject(id: string): Promise<ProjectSummary> {
  return fetchApi(`/api/projects/${id}`);
}

export async function getGraphStats(id: string): Promise<GraphStats> {
  return fetchApi(`/api/projects/${id}/graph`);
}

export async function queryGraph(id: string, q: string): Promise<QueryResult> {
  return fetchApi(`/api/projects/${id}/query?q=${encodeURIComponent(q)}`);
}

export async function rebuildGraph(id: string): Promise<{
  mode: "direct" | "agent";
  status: string;
  task_id?: string;
  agent?: string;
  project?: string;
  nodes?: number;
  edges?: number;
  error?: string;
}> {
  const res = await fetch(`${BASE_URL}/api/projects/${id}/rebuild`, { method: "POST" });
  return res.json();
}

// --- Project CRUD ---

export interface CreateProjectPayload {
  name: string;
  path: string;
}

export async function createProject(payload: CreateProjectPayload): Promise<ProjectSummary["project"]> {
  const res = await fetch(`${BASE_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function deleteProject(id: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE_URL}/api/projects/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function discoverDirs(path: string = "~"): Promise<{
  directories: { name: string; path: string; has_git: boolean }[];
  parent: string;
}> {
  return fetchApi(`/api/discover?path=${encodeURIComponent(path)}`);
}

// --- Graph Topology ---

export interface GraphTopology {
  nodes: { id: string; label: string; kind: string; community: number; file: string }[];
  edges: { source: string; target: string; kind: string }[];
}

// --- Extracted (LLM) Edges ---
// Edges extracted by an LLM agent from project findings, overlaid on the
// topology graph with a distinctive dashed indigo style in the dashboard.

export interface ExtractedEdge {
  name: string;
  kind: string;
  confidence: number;
  context: string;
  relationships: [string, string][];
  source_file: string;
  source: string;
}

export async function getExtractedEdges(
  projectId: string,
): Promise<{ edges: ExtractedEdge[] }> {
  return fetchApi(`/api/projects/${projectId}/extracted-edges`);
}

export interface CommunityInfo {
  id: string;
  name: string;
  size: number;
}

export interface FlowInfo {
  id: string;
  name: string;
  criticality: number;
  node_ids: string[];
}

export async function getGraphTopology(id: string): Promise<GraphTopology> {
  return fetchApi(`/api/projects/${id}/graph/topology`);
}

export async function getGraphCommunities(id: string): Promise<{ communities: CommunityInfo[] }> {
  return fetchApi(`/api/projects/${id}/graph/communities`);
}

export async function getGraphFlows(id: string): Promise<{ flows: FlowInfo[] }> {
  return fetchApi(`/api/projects/${id}/graph/flows`);
}

// --- Agent Dispatch ---

export async function dispatchTask(
  projectId: string,
  payload: { target_agent: string; instruction: string; priority?: string }
): Promise<{ task_id: string; status: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/dispatch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function listDispatches(projectId: string): Promise<{
  dispatches: { task_id: string; target_agent: string; instruction: string; status: string; dispatched_at: string }[];
}> {
  return fetchApi(`/api/projects/${projectId}/dispatches`);
}

// --- Agent Registration ---
export async function registerAgent(
  projectId: string,
  payload: { agent: string; version?: string; project_path: string; capabilities?: string[] }
): Promise<{ status: string; agent: string; project: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/register-agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// --- Agent Unregistration ---
export async function unregisterAgent(
  projectId: string,
  agentId: string
): Promise<{ deleted: boolean; agent_id: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/agents/${agentId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// --- Agent Capability Matching ---
export async function matchAgents(
  projectId: string,
  need: string,
): Promise<{ matches: AgentInfo[] }> {
  return fetchApi(`/api/projects/${projectId}/agents/match?need=${encodeURIComponent(need)}`);
}

// --- Known Agents ---
export interface KnownAgent {
  name: string;
  display: string;
  description: string;
  detect_cmd: string | null;
  default_version: string;
  default_capabilities: string[];
  installed: boolean;
}

export async function listKnownAgents(): Promise<{ agents: KnownAgent[] }> {
  return fetchApi("/api/agents/known");
}

export async function listRunnableAgents(): Promise<{ agents: string[] }> {
  return fetchApi("/api/agents/runnable");
}

// --- Knowledge Sources ---
export interface KnowledgeSourceResult {
  source_type: string;
  display_name: string;
  description: string;
  used_by: string[];
  found: boolean;
  path: string | null;
  size_bytes: number;
}

export async function getProjectKnowledge(projectId: string): Promise<{
  project_id: string;
  sources: KnowledgeSourceResult[];
}> {
  return fetchApi(`/api/projects/${projectId}/knowledge`);
}

export async function scanProjectKnowledge(projectId: string): Promise<{
  project_id: string;
  results: {
    source_type: string;
    display_name: string;
    found: boolean;
    status: string;
  }[];
}> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/knowledge/scan`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// --- Agent Task Board (Kanban) ---
export type AgentTaskStatus =
  | "triage" | "todo" | "ready" | "running" | "blocked" | "done" | "archived";

export interface AgentTask {
  id: string;
  project: string;
  title: string;
  instruction: string;
  status: AgentTaskStatus;
  assignee: string | null;
  priority: number;
  dependencies: string[];
  acceptance_criteria: string;
  result: string | null;
  created_at: string;
  updated_at: string;
  workspace_path: string | null;
}

export interface CreateAgentTaskPayload {
  title: string;
  instruction: string;
  assignee?: string | null;
  priority?: number;
  dependencies?: string[];
  acceptance_criteria?: string;
}

export interface UpdateAgentTaskPayload {
  status?: AgentTaskStatus;
  assignee?: string | null;
  result?: string;
  workspace_path?: string;
}

export async function listAgentTasks(projectId: string, status?: AgentTaskStatus): Promise<AgentTask[]> {
  const q = status ? `?status=${status}` : "";
  return fetchApi(`/api/projects/${projectId}/tasks${q}`);
}

export async function createAgentTask(projectId: string, payload: CreateAgentTaskPayload): Promise<AgentTask> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project: projectId, ...payload }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function updateAgentTask(projectId: string, taskId: string, payload: UpdateAgentTaskPayload): Promise<AgentTask> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getTaskDiff(projectId: string, taskId: string): Promise<{ diff: string; branch: string }> {
  return fetchApi(`/api/projects/${projectId}/tasks/${taskId}/diff`);
}

export async function mergeTask(
  projectId: string,
  taskId: string,
  target?: string,
  remote?: boolean,
): Promise<{ merged: boolean; output: string; target: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, remote }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getBranches(projectId: string): Promise<{
  current: string;
  branches: { name: string; remote: boolean }[];
}> {
  return fetchApi(`/api/projects/${projectId}/branches`);
}

export interface TaskProgressItem {
  task_id: string;
  seq: number;
  kind: string; // milestone | tool | text | error | summary
  message: string;
  ts: string;
}

export async function getTaskProgress(
  projectId: string,
  taskId: string,
): Promise<{ items: TaskProgressItem[] }> {
  return fetchApi(`/api/projects/${projectId}/tasks/${taskId}/progress`);
}

export async function listWorkers(projectId: string): Promise<{ running: string[] }> {
  return fetchApi(`/api/projects/${projectId}/workers`);
}

export async function startWorker(
  projectId: string,
  taskId: string,
): Promise<{ started: boolean; running: boolean }> {
  const res = await fetch(
    `${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/worker/start`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function stopWorker(
  projectId: string,
  taskId: string,
): Promise<{ stopped: boolean }> {
  const res = await fetch(
    `${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/worker/stop`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
