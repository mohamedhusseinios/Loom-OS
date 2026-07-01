# The filesystem protocol

Agents never call an API. They write files into `~/.loom/inbox/<project>/`, and the daemon reacts. This is the entire integration contract between an agent and Loom OS — no SDK, no auth required (an optional `--auth-token` team mode exists for multi-user setups, but the filesystem protocol itself needs none).

## Inbox file table

| File | Effect |
|------|--------|
| `register.json` | Upserts agent + project, triggers an initial full graph build |
| `heartbeat.json` | Marks agent online (offline after ~5 min of silence) |
| `finding-*.md` | Markdown + YAML frontmatter; if it references code `files`, queues an incremental graph update |
| `decision-*.md` | Architecture decision record (indexed as a finding) |
| `task-*.json` | A dispatched task (daemon → agent; written when the dashboard calls `POST /api/projects/{id}/dispatch`) |

After processing, each file is moved to `inbox/<project>/.processed/`. Persistent state lives in `~/.loom/state.db` (SQLite) and `~/.loom/daemon.log`.

## Directory layout

```
~/.loom/
├── inbox/
│   ├── my-project/
│   │   ├── register.json
│   │   ├── heartbeat.json
│   │   ├── finding-*.md
│   │   ├── decision-*.md
│   │   ├── task-*.json
│   │   └── .processed/       ← files moved here after processing
│   └── another-project/
├── state.db                  ← SQLite registry (agents, projects, tasks)
└── daemon.log
```

## Data flow

```
watcher.py   watchdog observer on ~/.loom/inbox (recursive). Extracts <project>
             from the path, marshals events onto the asyncio loop via
             run_coroutine_threadsafe.
   ↓ (project, filepath)
router.py    Router.handle_file dispatches by filename to _handle_* methods,
             then moves the file to .processed/. Emits WsEvents onto an
             asyncio.Queue. Rate-limits graph updates to 1 / 30s / project.
   ↓
registry.py  AgentRegistry: aiosqlite over ~/.loom/state.db. Tables: agents,
             projects, tasks. CRUD + graph-stat persistence.
graph_engine.py  GraphEngine: build/update/query/stats/topology/communities/flows.
api.py       FastAPI routes + WebSocket fan-out.
```

## Processing rules

1. **Atomic per file** — each file is processed independently; failure doesn't block others.
2. **Processed → archived** — after successful processing, the file moves to `.processed/`, keeping the inbox clean.
3. **Deduplicate** — rewriting the same file overwrites previously extracted nodes.
4. **Rate limit** — at most one incremental Graphify update per project per 30 seconds (`MIN_UPDATE_INTERVAL`). Rapid writes are batched.
5. **Idempotent task dispatch** — `task-*.json` creation uses `INSERT OR IGNORE` on `task_id` in the registry, so the watcher reprocessing the same dropped file is a safe no-op and never double-broadcasts a WebSocket event.

## Extraction on findings

When a `finding-*.md` or `decision-*.md` file is processed, the daemon also runs an **extractor pipeline** (a zero-dependency `RegexExtractor`, optionally an LLM-backed extractor) over the body text and persists any extracted entities/relationships as sidecar edges. See [The knowledge graph](knowledge-graph.md) and [Custom extractor plugin](../guides/custom-extractor-plugin.md).

## See also

- [Connect Claude Code](../guides/connect-claude-code.md) — concrete `register.json` / `heartbeat.json` examples and the `loom-client` SDK.
- [API reference](../reference/api.md) — the REST/WebSocket surface the dashboard uses to read this same state.
