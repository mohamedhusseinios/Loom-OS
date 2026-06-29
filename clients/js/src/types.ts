export interface RegisterPayload {
  agent: string;
  version: string;
  project: string;
  project_path: string;
  capabilities: string[];
}

export interface HeartbeatPayload {
  agent: string;
  project: string;
  status: string;
  timestamp: string;
}

export interface FindingPayload {
  agent: string;
  project: string;
  type: string;
  files: string[];
  timestamp: string;
  title: string;
  body: string;
}

export interface TaskPayload {
  type: string;
  task_id: string;
  target_agent: string;
  instruction: string;
  priority: string;
  dispatched_by: string;
  timestamp: string;
}