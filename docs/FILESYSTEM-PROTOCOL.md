# Filesystem Protocol

Agents communicate with Loom OS **exclusively through the filesystem**. No SDK, no API client, no authentication required. Every agent writes to `~/.loom/inbox/<project>/`.

## Directory Layout

```
~/.loom/
├── inbox/                  ← agents write here
│   ├── noor/               ← per-project subdirectory
│   │   ├── register.json       ← agent self-registration
│   │   ├── heartbeat.json      ← liveness ping
│   │   ├── finding-*.md        ← code analysis findings
│   │   ├── decision-*.md       ← architecture decisions
│   │   ├── task-*.json         ← dispatched task (daemon → agent)
│   │   └── .processed/         ← files moved here after processing
│   ├── mailo/
│   └── agentfiy/
├── state.db               ← SQLite registry (agents, projects, tasks)
└── daemon.log             ← daemon logs
```

## File Types (Agent → Daemon)

### `register.json` — Agent joins a project

```json
{
  "agent": "claude-code",
  "version": "2.1.190",
  "project": "noor",
  "project_path": "/abs/path/to/project",
  "capabilities": ["code-analysis", "refactoring"]
}
```

Written once when an agent starts working on a project. The daemon creates the project entry in its registry and queues an initial Graphify full build. Re-registration preserves graph stats (node/edge counts are not reset on re-reg).

### `heartbeat.json` — Agent liveness

```json
{
  "agent": "claude-code",
  "project": "noor",
  "status": "analyzing auth module",
  "timestamp": "2026-06-25T14:30:00Z"
}
```

Written periodically (recommended every ~60s). Refreshes the agent's `last_heartbeat` and keeps it `online`.

### `finding-*.md` — Knowledge contributions

```markdown
---
agent: claude-code
project: noor
type: code-analysis
files: [src/pipeline.py, src/ocr.py]
timestamp: 2026-06-25T14:35:00Z
---
# Auth Module Analysis

The auth pipeline uses JWT with Redis-backed session storage...
```

Free-form markdown with YAML frontmatter. If `files` references code files, it triggers an incremental graph update (rate-limited to one per project per 30s). The daemon also runs the **extractor pipeline** (RegexExtractor + optional LLMExtractor) on the finding body and persists any extracted entities/relationships to the `ExtractedEdgeStore` sidecar. An `extraction:completed` WebSocket event is emitted when extraction produces results.

### `decision-*.md` — Architecture decisions

```markdown
---
agent: codex
project: noor
type: architecture-decision
status: proposed
---
# ADR: Switch to async OCR pipeline

## Context
The current sync OCR blocks the request loop...
```

Structured ADRs, processed as architecture-decision findings.

## File Types (Daemon → Agent)

### `task-*.json` — Dispatched task

When work is dispatched from the dashboard (`POST /api/projects/:id/dispatch`), the daemon drops a `task-*.json` into the target project's inbox **and** records it in the registry.

```json
{
  "type": "task",
  "task_id": "5f3c…",
  "target_agent": "claude-code",
  "instruction": "Review the auth module for race conditions",
  "priority": "high",
  "dispatched_by": "dashboard",
  "timestamp": "2026-06-26T10:00:00Z"
}
```

Task creation is idempotent: the registry row uses `INSERT OR IGNORE` on `task_id`, so the watcher reprocessing the same file is a safe no-op and never double-broadcasts.

## Processing Rules

1. **Atomic per file** — each file processed independently. Failure doesn't block others.
2. **Processed → archived** — after successful processing, the file moves to `.processed/`. Keeps the inbox clean.
3. **Deduplicate** — same file re-written overwrites previous extracted nodes.
4. **Rate limit** — at most one incremental Graphify update per project per 30 seconds (`MIN_UPDATE_INTERVAL`). Rapid writes are batched.

## Shared Context

The daemon auto-generates `.loom/SHARED_CONTEXT.md` per project, containing:
- Graph statistics (nodes, edges, communities)
- Community list with sizes
- Key symbols and knowledge sources
- Recent findings
- Agent roster with status

Agents can read this file directly from the filesystem or via `GET /api/projects/{id}/context`.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Malformed JSON / payload | Logged; `error` event pushed via WebSocket. File left in inbox (only moved on success). |
| Watchdog double-fire | Skipped gracefully (`path.exists()` check + `FileNotFoundError` guard). |
| Duplicate task | Registry `INSERT OR IGNORE` — no duplicate WS event emitted. |
