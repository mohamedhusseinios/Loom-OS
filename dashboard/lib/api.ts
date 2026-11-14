const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8472`
    : "http://localhost:8472");

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

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = process.env.NEXT_PUBLIC_LOOM_AUTH_TOKEN;
  if (token) {
    return { ...extra, Authorization: `Bearer ${token}` };
  }
  return extra;
}

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) },
  });
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
  const res = await fetch(`${BASE_URL}/api/projects/${id}/rebuild`, {
    method: "POST",
    headers: authHeaders(),
  });
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
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function deleteProject(id: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE_URL}/api/projects/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
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
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// --- Agent Capability Matching ---
export interface TeamStatus {
  auth_enabled: boolean;
  users: string[];
}

export async function getTeamStatus(): Promise<TeamStatus> {
  return fetchApi("/api/team/status");
}

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
    headers: authHeaders(),
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
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ project: projectId, ...payload }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function updateAgentTask(projectId: string, taskId: string, payload: UpdateAgentTaskPayload): Promise<AgentTask> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    headers: authHeaders({ "Content-Type": "application/json" }),
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
    { method: "POST", headers: authHeaders() },
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
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// --- Cross-Project Federation (Feature #5) ---

export interface FederatedStats {
  projects_indexed: number;
  total_nodes: number;
  total_edges: number;
  shared_symbols_count: number;
  shared_symbols: {
    symbol: string;
    projects: string[];
    count: number;
    total_degree: number;
  }[];
}

export interface FederatedQueryResult {
  query: string;
  results: {
    id: string;
    kind: string;
    semantic_score: number;
    structural_distance: number;
    project: string;
  }[];
}

export interface FederatedReference {
  project: string;
  id: string;
  label: string;
  kind: string;
  file: string;
  degree: number;
}

export interface FederatedReferencesResult {
  symbol: string;
  references: FederatedReference[];
}

export async function fetchFederatedStats(): Promise<FederatedStats> {
  return fetchApi("/api/federated/stats");
}

export async function fetchFederatedQuery(
  q: string,
  depth: number = 2,
  top_k: number = 10,
): Promise<FederatedQueryResult> {
  return fetchApi(`/api/federated/query?q=${encodeURIComponent(q)}&depth=${depth}&top_k=${top_k}`);
}

export async function fetchFederatedReferences(
  symbol: string,
): Promise<FederatedReferencesResult> {
  return fetchApi(`/api/federated/references?symbol=${encodeURIComponent(symbol)}`);
}

// --- Loom Agent (orchestration loop) ---

export interface AgentSettings {
  default_model: string;
  providers: { id: string; name: string; base_url: string; model_ids: string[] }[];
  api_keys_masked: Record<string, string | null>;
  has_keys: Record<string, boolean>;
}

export interface TaskSuggestion {
  id: string;
  project: string;
  task_id: string;
  action_id: string;
  action_label: string;
  confidence: number;
  prose: string;
  catalog_json: string;
  status: "pending" | "accepted" | "dismissed";
  jev_skipped: boolean;
  jev_input_tokens?: number;
  llm_prompt_tokens?: number;
  llm_completion_tokens?: number;
  escalated?: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentCostSummary {
  suggestion_count: number;
  jev_input_tokens: number;
  llm_prompt_tokens: number;
  llm_completion_tokens: number;
  llm_total_tokens: number;
  jev_cost_usd: number;
  escalated_count: number;
  accepted: number;
  dismissed: number;
  pending: number;
  escalation_rate: number;
  accept_rate: number;
  dismiss_rate: number;
  accept_rate_resolved: number;
  dismiss_rate_resolved: number;
}

export async function getAgentSettings(): Promise<AgentSettings> {
  return fetchApi("/api/agent/settings");
}

export async function updateAgentSettings(payload: {
  default_model?: string;
  providers?: AgentSettings["providers"];
  api_keys?: Record<string, string>;
}): Promise<AgentSettings> {
  const res = await fetch(`${BASE_URL}/api/agent/settings`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function agentChat(
  projectId: string,
  payload: { message: string; task_id?: string; chat_id?: string },
): Promise<{ chat_id: string; reply: string; suggestion_id: string | null }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/agent/chat`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(detail.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function suggestTask(projectId: string, taskId: string): Promise<TaskSuggestion> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/suggest`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getPendingSuggestion(
  projectId: string,
  taskId: string,
): Promise<TaskSuggestion | null> {
  const data = await fetchApi<{ suggestion: TaskSuggestion | null }>(
    `/api/projects/${projectId}/tasks/${taskId}/suggestion`,
  );
  return data.suggestion;
}

export async function acceptSuggestion(projectId: string, suggestionId: string): Promise<TaskSuggestion> {
  const res = await fetch(
    `${BASE_URL}/api/projects/${projectId}/suggestions/${suggestionId}/accept`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function dismissSuggestion(projectId: string, suggestionId: string): Promise<TaskSuggestion> {
  const res = await fetch(
    `${BASE_URL}/api/projects/${projectId}/suggestions/${suggestionId}/dismiss`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function implementTask(projectId: string, taskId: string): Promise<AgentTask> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/implement`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getAgentCostSummary(projectId: string): Promise<AgentCostSummary> {
  return fetchApi(`/api/projects/${projectId}/agent/cost-summary`);
}
