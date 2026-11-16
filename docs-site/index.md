# Loom OS

**Loom OS** is a unified agent memory fabric that weaves multiple AI coding agents into one shared, Graphify-powered knowledge graph per project.

Agents talk to Loom OS **only through the filesystem** — there's no required SDK, API client, or auth for local use. An agent drops a file into an inbox directory, and Loom OS picks it up, indexes it, and makes it available to every other agent working on the same project.

## Why Loom OS

When multiple AI coding agents work on the same codebase, they don't share context by default. One agent's findings, decisions, and architectural notes are invisible to the next. Loom OS closes that gap: every agent reads and writes into the same knowledge graph, so insights compound instead of evaporating between sessions.

## How it's built

Loom OS runs as two independent processes:

- **The daemon** — a Python service (FastAPI + uvicorn) that watches an inbox directory on the filesystem. When an agent drops in a registration, heartbeat, finding, decision, or task file, the daemon processes it, updates the project's knowledge graph, and persists state.
- **The dashboard** — a Next.js web application that acts as the control plane. It visualizes the knowledge graph, shows connected agents and their status, dispatches tasks, and explores cross-project federation — all by talking to the daemon over REST and WebSocket.

Because the only contract between an agent and Loom OS is "write a file to this folder," any agent that can write to the filesystem can participate — no integration library required. Optional helpers (`loom wire`, `loom-client`, `loom-mcp`, LangChain memory) make that path faster.

## What's next

1. **[Quickstart](quickstart.md)** — daemon + first agent in about five minutes.
2. **[Connect Claude Code](guides/connect-claude-code.md)** — register, heartbeat, and SDK options.
3. **[Hybrid search](guides/hybrid-search.md)** — text vs graph+vector modes.
4. **[CLI reference](reference/cli.md)** — every `loom` subcommand, including `loom wire`.
5. **[Full user guide](https://github.com/mohamedhusseinios/Loom-OS/blob/main/docs/USAGE.md)** — federation, team mode, workers, troubleshooting.
