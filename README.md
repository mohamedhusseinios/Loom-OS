# Agentic OS

Unified agent memory fabric. Links all AI coding agents on a single machine through a shared Graphify-powered knowledge graph. Agents communicate via filesystem hooks. Next.js dashboard for monitoring and querying.

## Architecture

```
Browser :3000 → Next.js Dashboard
                    ↓ REST + WebSocket
Agentic OS Daemon (Python/FastAPI) :8472
  ├── Watcher (watchdog) → ~/.agentic-os/inbox/
  ├── Router (dispatcher)
  ├── Graph Engine (Graphify)
  └── Agent Registry (SQLite)
        ↑ filesystem writes
Claude Code · Codex · Hermes
```

## Quick Start

```bash
# Install
git clone <repo>
cd agentic-os
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Start daemon
agentic-os

# In another terminal, start dashboard
cd dashboard && npm install && npm run dev
```

Open http://localhost:3000

## How Agents Connect

Agents write files to `~/.agentic-os/inbox/<project>/`:

```bash
# Register
echo '{"agent":"claude-code","version":"2.1","project":"noor","project_path":"~/projects/Noor","capabilities":["code-analysis"]}' > ~/.agentic-os/inbox/noor/register.json

# Heartbeat (every 60s)
echo '{"agent":"claude-code","project":"noor","status":"analyzing","timestamp":"2026-06-25T14:30:00Z"}' > ~/.agentic-os/inbox/noor/heartbeat.json

# Share findings
cat > ~/.agentic-os/inbox/noor/finding-auth.md << 'EOF'
---
agent: claude-code
project: noor
type: code-analysis
files: [src/auth.py]
---
# Auth Module
JWT with Redis sessions...
EOF
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/projects | List projects |
| GET | /api/projects/:id | Project detail + graph + agents |
| GET | /api/projects/:id/graph | Graph stats |
| GET | /api/projects/:id/query?q= | Query graph |
| GET | /api/projects/:id/agents | Agent list |
| POST | /api/projects/:id/rebuild | Force rebuild |
| WS | /ws | Live events |

## Development

```bash
# Daemon
pip install -e ".[dev]"
pytest tests/ -v

# Dashboard
cd dashboard && npm run dev
```
