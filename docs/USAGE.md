# How to Use Loom OS

**Loom OS** is a unified agent memory fabric that weaves multiple AI coding agents — Claude Code, Codex, Hermes, Cursor, and more — into one shared, Graphify-powered knowledge graph per project.

Agents talk to Loom OS **only through the filesystem**: they drop files into a per-project inbox and the daemon handles the rest. There is no SDK to install in your agent scripts, no API client library, and no external database infrastructure. A Next.js dashboard provides a real-time control plane.

---

## Table of Contents

1. [Prerequisites & Installation](#1-prerequisites--installation)
2. [Starting Loom OS](#2-starting-loom-os)
3. [Managing Projects](#3-managing-projects)
4. [Connecting & Wiring AI Agents](#4-connecting--wiring-ai-agents)
   - [Zero-Config Auto-Wiring (`loom wire`)](#zero-config-auto-wiring-loom-wire)
   - [Model Context Protocol (MCP)](#model-context-protocol-mcp)
   - [Filesystem Protocol (Inbox)](#filesystem-protocol-inbox)
5. [Using the Dashboard Control Plane](#5-using-the-dashboard-control-plane)
6. [Task Board & Autonomous Workers](#6-task-board--autonomous-workers)
7. [Cross-Project Graph Federation](#7-cross-project-graph-federation)
8. [Team Mode & Authentication](#8-team-mode--authentication)
9. [CLI Quick Reference](#9-cli-quick-reference)
10. [Troubleshooting & FAQs](#10-troubleshooting--faqs)

---

## 1. Prerequisites & Installation

### Requirements
- **Python:** 3.11 or higher
- **Node.js:** 20 or higher
- **Git:** Git 2.25+ installed and available on `PATH`

### Installation

Install Loom OS from PyPI:

```bash
# Base install — zero external database, code AST builds require no LLM keys
pip install loom-os
```

Or install from source in editable mode:

```bash
git clone https://github.com/mohamedhusseinios/Loom-OS.git
cd Loom-OS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

> **Optional LLM extraction:**  
> If you want optional semantic edge extraction using local or remote LLMs (Ollama, OpenAI, Claude):  
> `pip install loom-os[llm]`  
> The default code AST parser runs completely offline without any API keys.

---

## 2. Starting Loom OS

Loom OS runs as two lightweight processes:
1. **The Python Daemon** (`FastAPI` + `uvicorn` on port `8472`): Watches inboxes, maintains the SQLite database, coordinates graph builds, and broadcasts WebSocket events.
2. **The Next.js Dashboard** (port `3000`): The visual user interface for exploring graphs, managing tasks, and reviewing diffs.

### Step 1: Start the Daemon

```bash
loom start
# Or specify host/port/reload for local development:
loom --port 8472 --reload
```

The daemon will initialise its state directory under `~/.loom/` (`state.db`, `inbox/`, `daemon.log`).

### Step 2: Start the Dashboard

In another terminal:

```bash
cd dashboard
npm install
npm run dev
```

Open **`http://localhost:3000`** in your browser.

| Process | Endpoint | Purpose |
|---|---|---|
| **Daemon** | `http://127.0.0.1:8472` | REST API + WebSocket (`/ws`) |
| **Dashboard** | `http://localhost:3000` | UI Control Plane (bilingual en/ar) |

---

## 3. Managing Projects

### Adding a Project via CLI

To track a local codebase with Loom OS, run:

```bash
loom init --project <project-name> --project-path /absolute/path/to/repo
```

This creates the project in `~/.loom/state.db`, sets up the inbox at `~/.loom/inbox/<project-name>/`, and kicks off an initial full AST graph build using Graphify.

### Adding a Project via the Dashboard

1. Navigate to `http://localhost:3000`.
2. Click **Add Project** in the sidebar.
3. Choose either **Browse** to select a directory on your machine or manually type the name and path.
4. Click **Create Project**. Loom OS will register the project and index the graph.

---

## 4. Connecting & Wiring AI Agents

Loom OS allows any coding agent to tap into the shared project memory using three primary approaches:

### Zero-Config Auto-Wiring (`loom wire`)

The fastest way to configure your tools is `loom wire`:

```bash
loom wire --project <project-name>
```

This automatically detects installed coding assistants (Claude Code, Cursor, Codex, Windsurf) and creates or updates their configuration files (e.g. `.mcp.json`, `.cursor/mcp.json`) pointing to Loom's MCP server.

### Model Context Protocol (MCP)

For MCP-compatible agents (like Claude Desktop or Claude Code), Loom OS provides `loom-mcp`:

```bash
loom-mcp
```

Add this server block to your agent's MCP settings (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "loom": {
      "command": "loom-mcp",
      "args": []
    }
  }
}
```

#### Available MCP Tools:
- `query_graph`: Ask natural-language questions about codebase structure and dependencies.
- `get_stats`: Retrieve current node, edge, and community counts.
- `add_finding`: Publish architectural decisions, patterns, or bug discoveries into Loom.
- `hybrid_search`: Run hybrid queries across lexical AST symbols, embeddings, and agent notes.

### Filesystem Protocol (Inbox)

Agents can operate **without any API client or MCP server** by writing simple JSON or Markdown files into `~/.loom/inbox/<project>/`. The daemon processes these files asynchronously and archives them into `.processed/`.

#### 1. Agent Self-Registration (`register.json`)
Drop `register.json` into `~/.loom/inbox/<project>/register.json`:

```json
{
  "agent_id": "claude-code-1",
  "agent_name": "claude-code",
  "version": "1.0.0",
  "project": "my-app",
  "capabilities": ["code-analysis", "refactoring"]
}
```

#### 2. Agent Keep-Alive (`heartbeat.json`)
Drop `heartbeat.json` periodically (agents without heartbeats for ~5 minutes are marked offline):

```json
{
  "agent_id": "claude-code-1"
}
```

#### 3. Submitting Findings (`finding-<id>.md`)
When an agent analyzes code or discovers a bug, it drops a markdown file with YAML frontmatter:

```markdown
---
agent: claude-code-1
project: my-app
type: bug-report
files:
  - src/auth/jwt.py
tags:
  - security
  - auth
---

# Expired Token Verification Bug
The token validation function fails to check the `exp` claim when the algorithm is set to `none`.
```

#### 4. Architecture Decision Records (`decision-<id>.md`)
Document system decisions with `decision-*.md`:

```markdown
---
agent: claude-code-1
project: my-app
title: Use SQLite WAL Mode for High-Concurrency State
status: accepted
tags:
  - database
  - architecture
---

# Decision
We enable SQLite WAL mode to allow concurrent background workers without database locking.
```

---

## 5. Using the Dashboard Control Plane

The Next.js dashboard provides a full visual command center:

- **Graph Explorer:** Interactive visual graph of your codebase (Cytoscape / CoSE Bilkent layout). Click any file, class, or function node to view incoming/outgoing relationships, callers, and related findings.
- **Agent Directory:** Live view of all registered agents, their current status (`online`, `working`, `offline`), and declared capabilities.
- **Hybrid Search:** Search bar in the top navigation allowing natural-language queries across:
  - Code AST nodes (functions, classes, files)
  - Semantic vector embeddings
  - Agent findings and decision records
- **Bilingual Interface:** Supports English (`en`) and Arabic (`ar`) with complete Right-To-Left (RTL) mirroring. Toggle locales at any time in the top-right menu.

---

## 6. Task Board & Autonomous Workers

Loom OS includes a 7-state Kanban task board (**Todo · Ready · Running · Blocked · Done**) with automated dependency resolution and isolated worker execution.

### Creating and Dispatching Tasks

1. In the dashboard, open your project and switch to the **Tasks** tab.
2. Click **Create Task**, specify the title, instructions, acceptance criteria, and assignee agent.
3. Optionally specify **Dependencies** (e.g., Task B depends on Task A).
4. When Task A reaches `Done`, Task B automatically promotes from `Todo` to `Ready`.

### Running the Autonomous Worker

To execute tasks automatically using an agent like Claude Code:

```bash
loom worker \
  --project my-app \
  --agent claude-code \
  --project-path /abs/path/to/my-app \
  --max-budget-usd 5.0
```

#### How Worker Execution Operates:
1. When a task is dragged to **Running** (or dispatched to a worker), the worker picks it up.
2. **Git Worktree Isolation:** The worker creates an isolated worktree at branch `loom/task-<id>`, keeping your main working tree untouched.
3. **Spend Capping:** The worker monitors token and tool spend against `--max-budget-usd`.
4. **Completion & Diffs:** Once done, the task moves to **Done** with an interactive diff generated directly against your base branch.
5. **Merging:** Click **Merge Task** in the dashboard to cleanly merge the worktree branch into your target branch (e.g. `main` or `dev`).

---

## 7. Cross-Project Graph Federation

If you manage microservices or multiple repositories, Loom OS supports org-wide cross-project graph federation:

- Query shared symbols, utilities, and models across all indexed projects.
- In the dashboard, open the **Federation** tab to explore cross-project dependencies and unified symbol index.
- Search API:
  ```bash
  curl "http://localhost:8472/api/federated/query?q=AuthService"
  ```

---

## 8. Team Mode & Authentication

By default, Loom OS operates in local developer mode (zero authentication required).

For team or remote setups:
1. Start the daemon with an authentication token:
   ```bash
   loom --port 8472 --auth-token "your-team-secret"
   # Or set the environment variable:
   export LOOM_AUTH_TOKEN="your-team-secret"
   ```
2. **Behavior:**
   - Read methods (`GET`, `OPTIONS`, `HEAD`) remain accessible so the dashboard and graph views stay responsive.
   - Write operations (`POST`, `PUT`, `DELETE`, `PATCH`) require the HTTP header:
     `Authorization: Bearer your-team-secret`
3. In remote setups, specify the daemon's URL in the dashboard:
   ```bash
   export NEXT_PUBLIC_API_URL="http://192.168.1.50:8472"
   export NEXT_PUBLIC_WS_URL="ws://192.168.1.50:8472/ws"
   npm run dev
   ```

---

## 9. CLI Quick Reference

```bash
# Daemon
loom start                                     # Start daemon on :8472
loom --port 8472 --host 0.0.0.0                # Custom host/port
loom --auth-token <secret>                     # Enable team auth mode

# Projects
loom init --project <name> --project-path <path>   # Track new project
loom list-projects                             # List tracked projects

# Agents & Wiring
loom detect-agents                             # Discover agents on machine
loom wire --project <name>                     # Auto-wire MCP configurations
loom register --agent <name> --project <name> --project-path <path>  # Register agent
loom unregister --agent <name> --project <name>                      # Remove agent

# Tasks & Workers
loom worker --project <name> --agent <name> --project-path <path>    # Start task worker
  --max-budget-usd 5.0                         # Budget cap per task

# MCP
loom-mcp                                       # Start Model Context Protocol server
```

---

## 10. Troubleshooting & FAQs

### The dashboard shows "Disconnected" or WebSocket error
- Ensure the daemon is running (`loom start` on port `8472`).
- Both `http://localhost:3000` and `http://127.0.0.1:3000` are permitted by CORS.
- The WebSocket client connects to `ws://127.0.0.1:8472/ws` to avoid dual-stack IPv6 (`::1`) loopback issues.

### My agent wrote a finding, but it didn't appear in the graph
- Check `~/.loom/inbox/<project>/.processed/`. If the file was moved there, the daemon successfully read it.
- To prevent AST update storms, graph rebuilds are debounced (maximum 1 rebuild per 30 seconds per project).

### `git worktree add` error when running a task
- Ensure your project directory is a clean Git repository with at least one commit on your initial branch.
- If a previous task crashed, Loom automatically recovers by reusing or cleaning up existing `loom/task-<id>` branches upon task retry.

---

*For architecture details, refer to the [Architecture Guide](ARCHITECTURE.md). For file format specifications, see the [Filesystem Protocol](FILESYSTEM-PROTOCOL.md).*
