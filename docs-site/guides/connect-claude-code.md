# Connect Claude Code

Any agent that can write files can participate in Loom OS. This guide shows the two ways to register an agent and keep it marked online: the raw filesystem protocol, and the `loom-client` convenience SDKs.

## Option A: raw `register.json`

Write directly to the inbox — no dependency needed:

```bash
mkdir -p ~/.loom/inbox/my-project
cat > ~/.loom/inbox/my-project/register.json <<'EOF'
{
  "agent": "claude-code",
  "version": "2.1.190",
  "project": "my-project",
  "project_path": "/abs/path/to/my-project",
  "capabilities": ["code-analysis", "refactoring"]
}
EOF
```

The daemon's watcher picks this up, upserts the agent + project in `~/.loom/state.db`, and queues an initial full Graphify build. Re-registering the same agent/project preserves existing graph stats (node/edge counts aren't reset).

Then keep the agent marked online with a periodic heartbeat (recommended every ~60s — an agent goes offline after ~5 minutes of silence):

```bash
cat > ~/.loom/inbox/my-project/heartbeat.json <<'EOF'
{
  "agent": "claude-code",
  "project": "my-project",
  "status": "analyzing auth module",
  "timestamp": "2026-06-25T14:30:00Z"
}
EOF
```

A simple heartbeat loop from a shell script or agent hook:

```bash
while true; do
  cat > ~/.loom/inbox/my-project/heartbeat.json <<EOF
{"agent": "claude-code", "project": "my-project", "status": "working", "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOF
  sleep 60
done
```

## Option B: the `loom-client` SDK

The repo ships convenience SDKs — Python (`loom-client`) and a matching npm package (`clients/js`, package name `loom-client`) — that validate payloads with Pydantic/TypeScript models before writing the same inbox files. The raw-file path above is fully supported either way; these are one-liners, not a replacement protocol.

Python:

```python
from loom_client import LoomClient

client = LoomClient()  # defaults to ~/.loom

client.register(
    project="my-project",
    agent="claude-code",
    project_path="/abs/path/to/my-project",
    capabilities=["code-analysis"],
)

client.heartbeat(project="my-project", agent="claude-code", status="analyzing auth module")

client.finding(
    project="my-project",
    agent="claude-code",
    title="Auth module analysis",
    body="The auth pipeline uses JWT with Redis-backed session storage...",
    files=["src/auth.py"],
)
```

Each method (`register`, `heartbeat`, `finding`, `task`) validates the payload and writes the correctly-named file (`register.json`, `heartbeat.json`, `finding-<slug>-<timestamp>.md` with YAML frontmatter, `task-<id>.json`) into `~/.loom/inbox/<project>/`.

## Verify it worked

Once registered, the agent should appear in the dashboard's Agents panel for the project (**http://localhost:3000**), and `GET /api/projects/:id/agents` should list it with `status: "online"`.

## See also

- [The filesystem protocol](../concepts/filesystem-protocol.md) — the full inbox file table and processing rules.
- [CLI reference](../reference/cli.md) — `loom register` / `loom init` as a CLI alternative to writing `register.json` by hand.
