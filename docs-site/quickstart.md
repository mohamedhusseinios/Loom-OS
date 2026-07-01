# Quickstart

Get a daemon and dashboard running, register your first agent, and see it show up in the graph — in about 5 minutes.

## 1. Install and start the daemon

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install loom-os
loom --port 8472
```

This starts the Loom daemon (FastAPI + uvicorn) on `http://127.0.0.1:8472`. It watches `~/.loom/inbox/` for files and persists state to `~/.loom/state.db` (SQLite).

!!! note "No LLM keys required"
    The base install works without any LLM. If you want optional LLM-powered extraction (Ollama / OpenAI / Claude), install with `pip install loom-os[llm]` instead — see [Knowledge graph](concepts/knowledge-graph.md).

## 2. Register an agent

Drop a `register.json` into the inbox for your project. Create the directory and file directly:

```bash
mkdir -p ~/.loom/inbox/my-project
cat > ~/.loom/inbox/my-project/register.json <<'EOF'
{
  "agent": "claude-code",
  "version": "1.0",
  "project": "my-project",
  "project_path": "/abs/path/to/my-project",
  "capabilities": ["code-analysis"]
}
EOF
```

The daemon's inbox watcher picks this up, upserts the agent and project into its registry, and kicks off an initial full Graphify build of `project_path`. See [The filesystem protocol](concepts/filesystem-protocol.md) for the full file table and processing rules.

## 3. Start the dashboard

In a second terminal:

```bash
cd dashboard
npm install
npm run dev
```

Open **http://localhost:3000**. The daemon must be running for the dashboard to show data — it talks to `127.0.0.1:8472` over REST and a single `/ws` WebSocket.

## What's next

- [The filesystem protocol](concepts/filesystem-protocol.md) — the full inbox file table (findings, decisions, tasks) and how the daemon processes each one.
- [The knowledge graph](concepts/knowledge-graph.md) — how Graphify builds and updates the per-project graph.
- [Connect Claude Code](guides/connect-claude-code.md) — register agents via the `loom-client` SDK, plus the heartbeat loop.
- [CLI reference](reference/cli.md) — every `loom` subcommand and flag.
