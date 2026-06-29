import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { LoomClient } from "../src/index";

describe("LoomClient", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "loom-test-"));
  });

  test("register writes valid JSON", () => {
    const client = new LoomClient(tmpDir);
    const filePath = client.register({
      project: "my-proj",
      agent: "claude-code",
      project_path: "/tmp",
      capabilities: ["code-analysis"],
    });
    expect(fs.existsSync(filePath)).toBe(true);
    const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    expect(data.agent).toBe("claude-code");
    expect(data.project).toBe("my-proj");
    expect(data.capabilities).toEqual(["code-analysis"]);
  });

  test("finding writes markdown with frontmatter", () => {
    const client = new LoomClient(tmpDir);
    const filePath = client.finding({
      project: "p",
      agent: "a",
      title: "Auth Review",
      body: "Found a bug",
      files: ["src/auth.ts"],
      type: "code-analysis",
    });
    expect(filePath).toMatch(/finding-.*\.md$/);
    const content = fs.readFileSync(filePath, "utf-8");
    expect(content.startsWith("---")).toBe(true);
    expect(content).toContain("agent: a");
    expect(content).toContain("Found a bug");
  });

  test("task writes valid JSON", () => {
    const client = new LoomClient(tmpDir);
    const filePath = client.task({
      project: "p",
      title: "Fix bug",
      instruction: "Fix the auth bug",
      target_agent: "codex",
      priority: "high",
    });
    expect(filePath).toMatch(/task-.*\.json$/);
    const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    expect(data.target_agent).toBe("codex");
    expect(data.priority).toBe("high");
  });

  test("heartbeat writes valid JSON", () => {
    const client = new LoomClient(tmpDir);
    const filePath = client.heartbeat({
      project: "p",
      agent: "a",
      status: "working",
    });
    expect(fs.existsSync(filePath)).toBe(true);
    const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    expect(data.agent).toBe("a");
    expect(data.status).toBe("working");
  });
});