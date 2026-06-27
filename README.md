<div align="center">

<img src="docs/branding/loom-icon-warp-256.png" alt="Loom OS" width="120" height="120" />

# Loom OS

**Unified agent memory fabric**

</div>

Weaves all your AI coding agents into one shared, [Graphify](https://github.com/nousresearch/graphify)-powered knowledge graph per project. Agents talk to Loom OS only through the filesystem — no SDK, no API client, no auth. A Next.js dashboard is the control plane.

> **Status:** v0.1.0 — daemon + dashboard working, 38+ tests passing, smoke-tested end-to-end. Includes project CRUD, interactive graph explorer, agent management with task dispatch, Kanban task board with isolated worker execution, and a bilingual (en/ar) dashboard.
>
> The product is **Loom OS**. The CLI/package is **`loom`**. The repo and docs are **`agentic-os`** — same project, different identifiers.

---

## Quick Start

```bash
git clone https://github.com/mohamedhusseinios/agentic-os.git
cd agentic-os

# Python daemon
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dashboard
cd dashboard && npm install

# Run both (stops on Ctrl+C)
./run.sh
```

| What | Where |
|------|-------|
| Daemon | `http://127.0.0.1:8472` |
| Dashboard | `http://localhost:3000` |

**Prerequisites:** Python 3.11+, Node.js 20+, `pip install graphifyy`

---

## How It Works

```
Browser :3000 ──▶  ┌──────────────────────────────────┐
                   │       Next.js Dashboard          │
                   └──────────────┬───────────────────┘
                                  │ REST + WebSocket
┌─────────────────────────────────┼───────────────────┐
│                  Loom Daemon (Python)                │
│  Watcher ──▶ Router ──▶ Graph Engine                │
│                │                │                   │
│           Registry (SQLite) ◀───┘                   │
└─────────────────────────────────────────────────────┘
     ▲                  ▲                  ▲
     │                  │                  │
  ~/inbox/noor       ~/inbox/mailo     ~/inbox/agentfiy
  Claude Code           Codex              Hermes
```

Agents drop files into `~/.loom/inbox/<project>/` — `register.json`, `heartbeat.json`, `finding-*.md`, `decision-*.md`. The daemon watches, processes, builds knowledge graphs, and pushes live updates to the dashboard via WebSocket. Work can be dispatched back to agents through the dashboard's task board.

---

## Documentation

| Guide | Covers |
|-------|--------|
| [Architecture](docs/ARCHITECTURE.md) | Deep dive into the two-process design, module map, data flow, and design principles |
| [Filesystem Protocol](docs/FILESYSTEM-PROTOCOL.md) | Full spec of the inbox protocol — every file type, format, and processing rule |
| [API Reference](docs/API.md) | Complete REST + WebSocket API with all endpoints and event types |
| [Dashboard Guide](docs/DASHBOARD.md) | Page-by-page tour, tech stack, i18n, and component map |
| [Task Board & Worker](docs/TASK-BOARD.md) | Kanban lifecycle, worker execution model, safety guarantees, and git worktree isolation |
| [Agent Lifecycle](docs/AGENT-LIFECYCLE.md) | Registration → contribution → dispatch flow, agent status, and shared context |
| [Development Guide](docs/DEVELOPMENT.md) | Setup, project structure, test suite, daemon patterns, and contribution conventions |

### Additional Docs

- [Design spec](docs/superpowers/specs/2026-06-25-agentic-os-design.md) — original system design
- [Dashboard features design](docs/superpowers/specs/2026-06-26-agentic-os-dashboard-features-design.md)
- [Implementation plan](docs/plans/2026-06-25-agentic-os-implementation.md)
- [Dashboard features plan](docs/plans/2026-06-26-dashboard-features-implementation.md)
- [Competitor gap-closure roadmap](docs/plans/2026-06-26-competitor-gap-closure-implementation.md)
  - [Competitor analysis report](docs/reports/26-06-2026_Competitors_report/report.md)

---

## Development

```bash
source .venv/bin/activate
pytest tests/ -v                          # full suite
bash scripts/smoke-test.sh                # end-to-end
cd dashboard && npm run dev               # dashboard hot-reload
```

See [Development Guide](docs/DEVELOPMENT.md) for the full reference.

---

## Brand

Monochrome, geometric. **Warp** (an L woven on a loom) is the primary mark; **Lattice** (an L traced through a knowledge graph) is the alternate.

| | Warp (primary) | Lattice (alternate) |
|---|---|---|
| Icon | <img src="docs/branding/loom-icon-warp-256.png" width="64" /> | <img src="docs/branding/loom-icon-lattice-512.png" width="64" /> |

- **Ink** `#141414` · **Paper** `#FFFFFF` · greys `#6F6F6F`, `#E5E5E5`
- **Wordmark** Space Grotesk 600, tracking −3.5%
- Full asset kit: [`docs/branding/`](docs/branding/README.md)

---

## License

MIT
