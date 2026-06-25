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

export async function rebuildGraph(id: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${id}/rebuild`, { method: "POST" });
  return res.json();
}
