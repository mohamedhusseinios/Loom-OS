# loom-client

Client SDK for **Loom OS** — validated one-liners for the inbox protocol.

Agents talk to Loom OS **only through the filesystem** (drop files in an inbox).
This SDK wraps that protocol with Pydantic-validated convenience methods so you
don't have to hand-craft JSON or YAML frontmatter.

## Install

```bash
cd loom-client
pip install -e ".[dev]"
```

## Quick start

```python
from loom_client import LoomClient

client = LoomClient()  # writes to ~/.loom/inbox/<project>/

# Register an agent for a project
client.register(project="my-proj", agent="claude-code",
                project_path="/code/my-proj",
                capabilities=["code-analysis", "review"])

# Keep the daemon informed that the agent is alive
client.heartbeat(project="my-proj", agent="claude-code", status="working")

# Drop a finding (markdown with YAML frontmatter)
client.finding(project="my-proj", agent="claude-code",
               title="Auth Service Review",
               body="The AuthService class handles login via BcryptHasher.",
               files=["src/auth.py"], type="code-analysis")

# Dispatch a task to another agent
client.task(project="my-proj", title="Fix auth bug",
            instruction="Fix the XSS vulnerability in the login form",
            target_agent="codex", priority="high")
```

## Methods

| Method | Inbox file | Purpose |
|--------|-----------|---------|
| `register(...)` | `register.json` | Upsert agent + project |
| `heartbeat(...)` | `heartbeat.json` | Mark agent online |
| `finding(...)` | `finding-<slug>-<ts>.md` | Markdown finding w/ YAML frontmatter |
| `task(...)` | `task-<id>.json` | Dispatch a task to another agent |

Each method validates its payload with Pydantic before writing, so malformed
files never reach the daemon's inbox.

## Schemas

The Pydantic models in `loom_client.models` are ported from the daemon's
`daemon/models.py` — the single source of truth. A round-trip test suite
verifies that files written by the SDK parse successfully with the daemon's
own models, catching schema drift.