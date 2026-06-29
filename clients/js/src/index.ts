import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import * as crypto from "crypto";
import type { RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload } from "./types";

function slugify(text: string): string {
  return text.trim().replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase() || "untitled";
}

function isoNow(): string {
  return new Date().toISOString();
}

export class LoomClient {
  private loomDir: string;

  constructor(loomDir?: string) {
    this.loomDir = loomDir || path.join(os.homedir(), ".loom");
  }

  private inbox(project: string): string {
    const dir = path.join(this.loomDir, "inbox", project);
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  register(opts: {
    project: string;
    agent: string;
    project_path: string;
    capabilities?: string[];
    version?: string;
  }): string {
    const payload: RegisterPayload = {
      agent: opts.agent,
      version: opts.version || "1.0",
      project: opts.project,
      project_path: opts.project_path,
      capabilities: opts.capabilities || [],
    };
    const filePath = path.join(this.inbox(opts.project), "register.json");
    fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
    return filePath;
  }

  heartbeat(opts: {
    project: string;
    agent: string;
    status?: string;
  }): string {
    const payload: HeartbeatPayload = {
      agent: opts.agent,
      project: opts.project,
      status: opts.status || "",
      timestamp: isoNow(),
    };
    const filePath = path.join(this.inbox(opts.project), "heartbeat.json");
    fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
    return filePath;
  }

  finding(opts: {
    project: string;
    agent: string;
    title: string;
    body: string;
    files?: string[];
    type?: string;
  }): string {
    const type = opts.type || "general";
    const files = opts.files || [];
    const slug = slugify(opts.title);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, -5);
    const filename = `finding-${slug}-${ts}.md`;
    const filePath = path.join(this.inbox(opts.project), filename);

    const frontmatter = `---
agent: ${opts.agent}
project: ${opts.project}
type: ${type}
files:
${files.length > 0 ? files.map((f) => `  - ${f}`).join("\n") : "  []"}
timestamp: ${isoNow()}
---
${opts.body}
`;
    fs.writeFileSync(filePath, frontmatter);
    return filePath;
  }

  task(opts: {
    project: string;
    title: string;
    instruction: string;
    target_agent: string;
    task_id?: string;
    priority?: string;
  }): string {
    const taskId = opts.task_id || crypto.randomBytes(6).toString("hex");
    const payload: TaskPayload = {
      type: "task",
      task_id: taskId,
      target_agent: opts.target_agent,
      instruction: opts.instruction,
      priority: opts.priority || "medium",
      dispatched_by: "sdk",
      timestamp: isoNow(),
    };
    const filePath = path.join(this.inbox(opts.project), `task-${taskId}.json`);
    fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
    return filePath;
  }
}

export { RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload } from "./types";