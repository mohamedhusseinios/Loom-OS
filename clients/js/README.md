# loom-client (JavaScript)

Client SDK for **Loom OS** — validated one-liners for the inbox protocol.

## Install

```bash
npm install loom-client
```

## Quick Start

```typescript
import { LoomClient } from "loom-client";

const client = new LoomClient();

// Register an agent
client.register({
  project: "my-app",
  agent: "claude-code",
  project_path: "/path/to/project",
  capabilities: ["code-analysis", "review"],
});

// Drop a finding
client.finding({
  project: "my-app",
  agent: "claude-code",
  title: "Auth service review",
  body: "AuthService uses bcrypt — good.",
  files: ["src/auth.py"],
  type: "code-analysis",
});

// Dispatch a task
client.task({
  project: "my-app",
  title: "Fix login bug",
  instruction: "Fix the redirect loop in login_handler",
  target_agent: "codex",
  priority: "high",
});
```

## API

### `new LoomClient(loomDir?)`

- `register({project, agent, project_path, capabilities?, version?})` → writes `register.json`
- `heartbeat({project, agent, status?})` → writes `heartbeat.json`
- `finding({project, agent, title, body, files?, type?})` → writes `finding-<slug>-<timestamp>.md`
- `task({project, title, instruction, target_agent, task_id?, priority?})` → writes `task-<id>.json`

## Raw-file path

The SDK is a convenience wrapper. You can always write files directly to `~/.loom/inbox/<project>/`.