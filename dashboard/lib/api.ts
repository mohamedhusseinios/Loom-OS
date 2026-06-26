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
