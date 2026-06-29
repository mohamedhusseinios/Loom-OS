# Loom OS Phase 2 — Client SDK (`loom-client`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Source spec:** [docs/superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md](../superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md) — Feature #5
> **Parent plan:** [docs/plans/2026-06-29-post-parity-roadmap-implementation.md](2026-06-29-post-parity-roadmap-implementation.md) — Phase 2

**Goal:** One-liners for the inbox protocol with schema validation. The raw-file path stays fully supported. No daemon changes — the SDK is purely additive.

**Architecture:** A new top-level `loom-client/` Python package (separate from the daemon) with Pydantic-validated methods that write to the correct inbox paths. An npm twin mirrors the API. Schemas are ported from `daemon/models.py` as the source of truth.

**Tech Stack:** Python 3.11+ (Pydantic), TypeScript (npm package).

## Global Constraints (inherited)

- **No daemon changes** — the SDK is purely additive.
- Filesystem inbox protocol preserved — the SDK wraps it, never replaces it.
- Raw-file path stays fully supported.
- Schema must track `daemon/models.py` to avoid drift.

---

## Task 5.1: Python package scaffolding (`loom-client/`)

**Files:**
- Create: `loom-client/pyproject.toml`
- Create: `loom-client/loom_client/__init__.py`
- Create: `loom-client/loom_client/models.py` (Pydantic schemas ported from daemon)
- Create: `loom-client/tests/test_models.py`

**Interfaces:**
- `loom_client/__init__.py` exports `LoomClient`.
- `loom_client/models.py` defines `RegisterPayload`, `HeartbeatPayload`, `FindingPayload`, `TaskPayload` — ported from `daemon/models.py` with the same field names and types.

- [ ] **Step 1: Create the package structure**

```bash
mkdir -p loom-client/loom_client
mkdir -p loom-client/tests
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "loom-client"
version = "0.1.0"
description = "Client SDK for Loom OS — validated inbox protocol one-liners"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
keywords = ["loom", "loom-os", "agent-memory", "agent-sdk"]
authors = [{ name = "Mohamed Hussien" }]
dependencies = [
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24.0"]

[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["loom_client*"]
```

- [ ] **Step 3: Create `models.py` (ported from daemon/models.py)**

```python
# loom-client/loom_client/models.py
"""Pydantic schemas for Loom inbox files.

Ported from daemon/models.py — the single source of truth.
If daemon schemas change, update these to match.
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class RegisterPayload(BaseModel):
    agent: str
    version: str = "1.0"
    project: str
    project_path: str
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatPayload(BaseModel):
    agent: str
    project: str
    status: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FindingPayload(BaseModel):
    """Frontmatter + body for a finding-*.md file."""
    agent: str
    project: str
    type: str = "general"  # code-analysis | architecture-decision | bug-report | general
    files: list[str] = Field(default_factory=list)
    timestamp: Optional[datetime] = None
    title: str = ""  # used for the filename
    body: str = ""   # markdown body after frontmatter


class TaskPayload(BaseModel):
    type: str = "task"
    task_id: str
    target_agent: str
    instruction: str
    priority: str = "medium"
    dispatched_by: str = "sdk"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Write the test**

```python
# loom-client/tests/test_models.py
import pytest
from loom_client.models import RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload


def test_register_payload_defaults():
    p = RegisterPayload(agent="claude-code", project="my-proj", project_path="/tmp")
    assert p.version == "1.0"
    assert p.capabilities == []


def test_finding_payload():
    p = FindingPayload(agent="claude-code", project="my-proj", title="Auth bug", body="Found XSS")
    assert p.type == "general"
    assert p.title == "Auth bug"


def test_task_payload():
    p = TaskPayload(task_id="abc123", target_agent="codex", instruction="Review PR")
    assert p.priority == "medium"
    assert p.dispatched_by == "sdk"
```

- [ ] **Step 5: Run tests**

Run: `cd loom-client && pip install -e ".[dev]" && pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add loom-client/
git commit -m "feat(sdk): scaffold loom-client Python package with ported models"
```

---

## Task 5.2: `LoomClient` class — register, heartbeat, finding, task

**Files:**
- Create: `loom-client/loom_client/client.py`
- Create: `loom-client/loom_client/__init__.py` (exports)
- Test: `loom-client/tests/test_client.py`

**Interfaces:**
- `LoomClient(loom_dir: str | None = None)` — defaults to `~/.loom`.
- `register(project, agent, capabilities=..., version=..., project_path=...) -> Path` — writes `register.json` to `~/.loom/inbox/<project>/`.
- `heartbeat(project, agent, status=...) -> Path` — writes `heartbeat.json`.
- `finding(project, agent, title, body, files=..., type=...) -> Path` — writes `finding-<slug>.md` with YAML frontmatter + body.
- `task(project, title, instruction, target_agent, task_id=..., priority=...) -> Path` — writes `task-<id>.json`.
- Each method validates with Pydantic and returns the file path written.

- [ ] **Step 1: Write the failing test**

```python
# loom-client/tests/test_client.py
import json
import pytest
from pathlib import Path
from loom_client import LoomClient


def test_register_writes_valid_json(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.register(
        project="my-proj",
        agent="claude-code",
        project_path=str(tmp_path),
        capabilities=["code-analysis", "review"],
    )
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["agent"] == "claude-code"
    assert data["project"] == "my-proj"
    assert data["capabilities"] == ["code-analysis", "review"]
    assert path.name == "register.json"
    assert "my-proj" in str(path)


def test_heartbeat_writes_valid_json(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.heartbeat(project="my-proj", agent="claude-code", status="working")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["agent"] == "claude-code"
    assert data["project"] == "my-proj"
    assert data["status"] == "working"
    assert "timestamp" in data


def test_finding_writes_markdown_with_frontmatter(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.finding(
        project="my-proj",
        agent="claude-code",
        title="Auth Service Review",
        body="The AuthService class handles login via BcryptHasher.",
        files=["src/auth.py"],
        type="code-analysis",
    )
    assert path.exists()
    assert path.name.startswith("finding-")
    assert path.suffix == ".md"
    content = path.read_text()
    assert content.startswith("---")
    assert "agent: claude-code" in content
    assert "project: my-proj" in content
    assert "type: code-analysis" in content
    assert "src/auth.py" in content
    # Body is after the second ---
    parts = content.split("---", 2)
    assert len(parts) >= 3
    assert "AuthService" in parts[2]


def test_task_writes_valid_json(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.task(
        project="my-proj",
        title="Fix auth bug",
        instruction="Fix the XSS vulnerability in the login form",
        target_agent="codex",
        priority="high",
    )
    assert path.exists()
    assert path.name.startswith("task-")
    assert path.suffix == ".json"
    data = json.loads(path.read_text())
    assert data["target_agent"] == "codex"
    assert data["instruction"] == "Fix the XSS vulnerability in the login form"
    assert data["priority"] == "high"
    assert "task_id" in data


def test_finding_filename_is_slugified(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.finding(
        project="p", agent="a", title="Auth Service Review!",
        body="body",
    )
    # Title is slugified — no spaces or special chars
    assert " " not in path.name
    assert "!" not in path.name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd loom-client && pytest tests/test_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'LoomClient'`

- [ ] **Step 3: Implement `LoomClient`**

```python
# loom-client/loom_client/client.py
"""LoomClient — validated one-liners for the Loom inbox protocol.

Each method validates the payload with Pydantic and writes the file to the
correct inbox path. The raw-file path stays fully supported — this is a
convenience wrapper, not a replacement.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from loom_client.models import (
    RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload,
)


def _slugify(text: str) -> str:
    """Convert a title to a filename-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip())
    return slug.strip("-").lower() or "untitled"


class LoomClient:
    """Write validated inbox files to the Loom daemon's filesystem inbox."""

    def __init__(self, loom_dir: str | None = None):
        self.loom_dir = Path(loom_dir or os.path.expanduser("~/.loom"))

    def _inbox(self, project: str) -> Path:
        d = self.loom_dir / "inbox" / project
        d.mkdir(parents=True, exist_ok=True)
        return d

    def register(
        self,
        project: str,
        agent: str,
        project_path: str,
        capabilities: list[str] | None = None,
        version: str = "1.0",
    ) -> Path:
        """Write register.json to the project inbox."""
        payload = RegisterPayload(
            agent=agent,
            version=version,
            project=project,
            project_path=project_path,
            capabilities=capabilities or [],
        )
        path = self._inbox(project) / "register.json"
        path.write_text(json.dumps(payload.model_dump(), indent=2))
        return path

    def heartbeat(
        self,
        project: str,
        agent: str,
        status: str = "",
    ) -> Path:
        """Write heartbeat.json to the project inbox."""
        payload = HeartbeatPayload(agent=agent, project=project, status=status)
        path = self._inbox(project) / "heartbeat.json"
        path.write_text(json.dumps(payload.model_dump(), indent=2, default=str))
        return path

    def finding(
        self,
        project: str,
        agent: str,
        title: str,
        body: str,
        files: list[str] | None = None,
        type: str = "general",
    ) -> Path:
        """Write a finding-<slug>.md file with YAML frontmatter + body."""
        payload = FindingPayload(
            agent=agent,
            project=project,
            type=type,
            files=files or [],
            title=title,
            body=body,
        )
        slug = _slugify(title)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"finding-{slug}-{timestamp}.md"
        path = self._inbox(project) / filename

        frontmatter = {
            "agent": payload.agent,
            "project": payload.project,
            "type": payload.type,
            "files": payload.files,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{payload.body}\n"
        path.write_text(content)
        return path

    def task(
        self,
        project: str,
        title: str,
        instruction: str,
        target_agent: str,
        task_id: str | None = None,
        priority: str = "medium",
    ) -> Path:
        """Write a task-<id>.json file to the project inbox."""
        if task_id is None:
            task_id = str(uuid.uuid4())[:12]
        payload = TaskPayload(
            task_id=task_id,
            target_agent=target_agent,
            instruction=instruction,
            priority=priority,
        )
        path = self._inbox(project) / f"task-{task_id}.json"
        path.write_text(json.dumps(payload.model_dump(), indent=2, default=str))
        return path
```

```python
# loom-client/loom_client/__init__.py
from loom_client.client import LoomClient
from loom_client.models import RegisterPayload, HeartbeatPayload, FindingPayload, TaskPayload

__all__ = ["LoomClient", "RegisterPayload", "HeartbeatPayload", "FindingPayload", "TaskPayload"]
```

- [ ] **Step 4: Run tests**

Run: `cd loom-client && pytest tests/ -v`
Expected: PASS (all model + client tests)

- [ ] **Step 5: Commit**

```bash
git add loom-client/
git commit -m "feat(sdk): implement LoomClient with register/heartbeat/finding/task methods"
```

---

## Task 5.3: Round-trip integration test (SDK → daemon processes it)

**Files:**
- Create: `loom-client/tests/test_roundtrip.py`

**Interfaces:**
- Test that an SDK-written `register.json` is byte-compatible with what the daemon expects — verify by parsing it with `daemon.models.RegisterPayload`.

- [ ] **Step 1: Write the test**

```python
# loom-client/tests/test_roundtrip.py
"""Round-trip test: SDK writes a file, daemon models parse it successfully.

This catches schema drift between the SDK and the daemon.
"""
import json
import sys
from pathlib import Path

# Add the daemon package to the path for this test
daemon_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(daemon_root))

from loom_client import LoomClient
from daemon.models import RegisterPayload, HeartbeatPayload, TaskPayload


def test_register_file_parses_with_daemon_models(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.register(
        project="roundtrip",
        agent="claude-code",
        project_path=str(tmp_path),
        capabilities=["code-analysis"],
        version="1.5",
    )
    data = json.loads(path.read_text())
    # Daemon's RegisterPayload should parse this without error
    payload = RegisterPayload(**data)
    assert payload.agent == "claude-code"
    assert payload.version == "1.5"
    assert payload.capabilities == ["code-analysis"]


def test_heartbeat_file_parses_with_daemon_models(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.heartbeat(project="rt", agent="codex", status="working")
    data = json.loads(path.read_text())
    payload = HeartbeatPayload(**data)
    assert payload.agent == "codex"
    assert payload.status == "working"


def test_task_file_parses_with_daemon_models(tmp_path):
    client = LoomClient(loom_dir=str(tmp_path))
    path = client.task(
        project="rt",
        title="Test task",
        instruction="Write tests",
        target_agent="codex",
        priority="high",
    )
    data = json.loads(path.read_text())
    payload = TaskPayload(**data)
    assert payload.target_agent == "codex"
    assert payload.priority == "high"
```

- [ ] **Step 2: Run tests**

Run: `cd loom-client && pytest tests/test_roundtrip.py -v`
Expected: PASS (SDK files are compatible with daemon models)

- [ ] **Step 3: Commit**

```bash
git add loom-client/tests/test_roundtrip.py
git commit -m "test(sdk): round-trip integration test — SDK files parse with daemon models"
```

---

## Task 5.4: npm twin (`clients/js/`)

**Files:**
- Create: `clients/js/package.json`
- Create: `clients/js/src/index.ts`
- Create: `clients/js/src/types.ts`
- Create: `clients/js/tests/index.test.ts`
- Create: `clients/js/README.md`

**Interfaces:**
- `LoomClient` class with `register()`, `heartbeat()`, `finding()`, `task()` — mirroring the Python SDK.
- Each method writes to the correct inbox path with the correct schema.

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "loom-client",
  "version": "0.1.0",
  "description": "Client SDK for Loom OS — validated inbox protocol one-liners",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "scripts": {
    "build": "tsc",
    "test": "jest"
  },
  "keywords": ["loom", "loom-os", "agent-memory", "agent-sdk"],
  "author": "Mohamed Hussien",
  "license": "MIT",
  "devDependencies": {
    "typescript": "^5.0.0",
    "@types/node": "^20.0.0",
    "@types/jest": "^29.0.0",
    "ts-jest": "^29.0.0",
    "jest": "^29.0.0"
  }
}
```

- [ ] **Step 2: Create `types.ts`**

```typescript
// clients/js/src/types.ts
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
```

- [ ] **Step 3: Create `index.ts`**

```typescript
// clients/js/src/index.ts
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
${files.map((f) => `  - ${f}`).join("\n")}
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
```

- [ ] **Step 4: Write the test**

```typescript
// clients/js/tests/index.test.ts
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
});
```

- [ ] **Step 5: Run tests (if Node is available)**

Run: `cd clients/js && npm install && npm test`
Expected: PASS (if jest is configured; otherwise verify TypeScript compiles with `npx tsc --noEmit`)

- [ ] **Step 6: Commit**

```bash
git add clients/js/
git commit -m "feat(sdk): add npm twin of loom-client with TypeScript types"
```

---

## Task 5.5: Examples + README

**Files:**
- Create: `loom-client/README.md`
- Create: `loom-client/examples/python_example.py`
- Create: `loom-client/examples/shell_example.sh`
- Create: `clients/js/README.md`

- [ ] **Step 1: Create Python example**

```python
# loom-client/examples/python_example.py
"""Example: using loom-client with Claude Code or any Python agent."""
from loom_client import LoomClient

client = LoomClient()

# Register your agent
client.register(
    project="my-web-app",
    agent="claude-code",
    project_path="/Users/me/projects/my-web-app",
    capabilities=["code-analysis", "review", "testing"],
)

# Send a heartbeat
client.heartbeat(project="my-web-app", agent="claude-code", status="working")

# Drop a finding
client.finding(
    project="my-web-app",
    agent="claude-code",
    title="Auth service uses weak hashing",
    body="The AuthService class uses MD5 for password hashing. Should use bcrypt.",
    files=["src/auth/service.py"],
    type="bug-report",
)

# Dispatch a task to another agent
client.task(
    project="my-web-app",
    title="Fix auth hashing",
    instruction="Replace MD5 with bcrypt in src/auth/service.py",
    target_agent="codex",
    priority="high",
)
```

- [ ] **Step 2: Create shell example**

```bash
#!/bin/bash
# loom-client/examples/shell_example.sh
# Example: using the inbox protocol directly from shell (no SDK needed)
# The SDK is a convenience — the raw-file path always works.

INBOX="$HOME/.loom/inbox/my-project"
mkdir -p "$INBOX"

# Register
cat > "$INBOX/register.json" << 'EOF'
{"agent": "claude-code", "version": "1.0", "project": "my-project", "project_path": "/Users/me/projects/my-project", "capabilities": ["code-analysis"]}
EOF

# Finding
cat > "$INBOX/finding-auth-review.md" << 'EOF'
---
agent: claude-code
project: my-project
type: code-analysis
files:
  - src/auth.py
---
The AuthService class handles login via BcryptHasher. Looks solid.
EOF

echo "Files written to $INBOX"
```

- [ ] **Step 3: Create `loom-client/README.md`**

```markdown
# loom-client

Client SDK for **Loom OS** — validated one-liners for the inbox protocol.

## Install

```bash
pip install loom-client
```

## Quick Start

```python
from loom_client import LoomClient

client = LoomClient()

# Register an agent
client.register(
    project="my-app",
    agent="claude-code",
    project_path="/path/to/project",
    capabilities=["code-analysis", "review"],
)

# Drop a finding
client.finding(
    project="my-app",
    agent="claude-code",
    title="Auth service review",
    body="AuthService uses bcrypt — good.",
    files=["src/auth.py"],
    type="code-analysis",
)

# Dispatch a task
client.task(
    project="my-app",
    title="Fix login bug",
    instruction="Fix the redirect loop in login_handler",
    target_agent="codex",
    priority="high",
)
```

## API

### `LoomClient(loom_dir=None)`

- `register(project, agent, project_path, capabilities=[], version="1.0")` → writes `register.json`
- `heartbeat(project, agent, status="")` → writes `heartbeat.json`
- `finding(project, agent, title, body, files=[], type="general")` → writes `finding-<slug>-<timestamp>.md`
- `task(project, title, instruction, target_agent, task_id=None, priority="medium")` → writes `task-<id>.json`

## Raw-file path

The SDK is a convenience wrapper. You can always write files directly to `~/.loom/inbox/<project>/` — see `examples/shell_example.sh`.
```

- [ ] **Step 4: Commit**

```bash
git add loom-client/README.md loom-client/examples/ clients/js/README.md
git commit -m "docs(sdk): add examples and README for loom-client"
```

---

## Verification

- [ ] `cd loom-client && pytest tests/ -v` — all Python SDK tests pass.
- [ ] Round-trip test confirms SDK-written files parse with `daemon.models.*` (no schema drift).
- [ ] `cd clients/js && npx tsc --noEmit` — TypeScript compiles without errors.
- [ ] npm tests pass (if Node.js is available).
- [ ] Python example runs without error against a temp `~/.loom` dir.
- [ ] **No daemon files modified** — the SDK is purely additive.