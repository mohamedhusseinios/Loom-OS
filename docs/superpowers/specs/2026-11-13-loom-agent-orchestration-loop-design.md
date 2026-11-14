# Loom Agent + Jev Orchestration Loop — Design

**Date:** 2026-11-13  
**Status:** Approved (design)  
**Related:**
- `docs/superpowers/specs/2026-06-27-agentic-os-kanban-task-board-design.md`
- `docs/superpowers/specs/2026-06-28-multi-agent-worker-runners-design.md`

---

## 1. Summary

Add a first-party **Loom agent** in the dashboard that:

1. Chats with the user about Kanban board tasks.
2. Runs an **orchestration loop** over project **graph memory**: Jev (TypeSafe System One) filters/ranks graph hits and helps choose next actions; a **main chat model** (default DeepSeek; BYOK + pluggable OpenAI-compatible models) writes human-language replies and suggestion prose.
3. Suggests the next step for human **Accept / Dismiss** (nothing executes until the user acts).
4. **Implements** via hybrid handoff: assign `loom-agent`, move task to Running, existing `loom worker` runs in a git worktree.

## 2. Decisions

| Fork | Decision |
|------|----------|
| Suggest vs auto-run | Suggest-only until Accept / Implement |
| Main chat model | DeepSeek by default; user API key; add other OpenAI-compatible models |
| Jev role | Not chat — filter/rank graph context + typed `choice` to help the main model |
| Context source | Project graph via `GraphEngine.hybrid_query` (+ task fields / findings) |
| Next-step catalog | Status-valid Loom actions + optional `loom-playbook.json` + graph-cited candidates |
| Triggers | Auto on Ready / Blocked / leave Running + manual Suggest / chat |
| Implement path | Hybrid: chat/loop plans; worker executes |

## 3. Architecture

```
Dashboard Loom Agent UI
    │  chat / suggest / accept / implement / settings
    ▼
Daemon agent_runtime
    │
    ▼
orchestrator
    │ 1. hybrid_query (broad)
    │ 2. Jev filter/rank nodes (noul/score)
    │ 3. Main model (chat + candidate labels)
    │ 4. Jev choice over catalog
    │ 5. Persist suggestion + WS
    ▼
SQLite (chats, suggestions, settings) + existing task APIs
    │
    └─ Implement → assignee=loom-agent, status=running → loom worker worktree
```

### Component responsibilities

| Unit | Purpose | Depends on |
|------|---------|------------|
| `jev_client` | TypeSafe `/v1/systemone` | `TYPESAFE_API_KEY` |
| `llm_client` | OpenAI-compatible chat | user settings / env |
| `orchestrator` | One suggest/chat cycle | graph_engine, jev, llm, registry |
| `agent_runtime` | Chat history + suggest/implement glue | orchestrator, registry |
| Dashboard panel | Chat, suggestion chip, BYOK settings | REST + WS |

## 4. Data model

### Tables (in `~/.loom/state.db`)

**`agent_settings`** (singleton row `id=1`):

- `default_model` TEXT (e.g. `deepseek-chat`)
- `providers_json` TEXT — list of `{id, name, base_url, model_ids[]}`
- `api_keys_json` TEXT — map provider_id → api_key (never returned raw on GET)

**`agent_chats`**: `id`, `project`, `task_id` NULLABLE, `created_at`, `updated_at`

**`agent_messages`**: `id`, `chat_id`, `role` (`user`/`assistant`/`system`), `content`, `created_at`

**`task_suggestions`**: `id`, `project`, `task_id`, `action_id`, `action_label`, `confidence`, `prose`, `catalog_json`, `status` (`pending`/`accepted`/`dismissed`), `jev_skipped` INT, `created_at`, `updated_at`

Unique constraint: at most one `pending` suggestion per `task_id`.

### Playbook file

Optional `{project_path}/loom-playbook.json`:

```json
{
  "steps": [
    {"id": "playbook.write_tests", "label": "Write failing tests first", "when": ["todo", "ready"]}
  ]
}
```

## 5. API

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects/{id}/agent/chat` | `{message, task_id?, chat_id?}` → reply + optional suggestion |
| POST | `/api/projects/{id}/tasks/{tid}/suggest` | Manual suggest |
| POST | `/api/projects/{id}/suggestions/{sid}/accept` | Apply Loom action if applicable; 409 if stale |
| POST | `/api/projects/{id}/suggestions/{sid}/dismiss` | Mark dismissed |
| POST | `/api/projects/{id}/tasks/{tid}/implement` | Assign `loom-agent`, status Running |
| GET/PUT | `/api/agent/settings` | Masked keys on GET |

WebSocket events: `agent:message`, `task:suggestion`.

## 6. Orchestration loop details

1. **Retrieve** — `hybrid_query(project_path, project, question=task.title + instruction)` top_k broad.
2. **Empty graph** — if no hits and no graph.json, return guidance to build graph; do not invent context.
3. **Jev filter** — fan-out `noul`/`score` questions per candidate node (“Is this relevant to the task?”); keep top N. On Jev failure: use top-N hybrid hits, set `jev_skipped`.
4. **Main model** — given filtered pack + chat history, produce assistant reply and optional candidate option labels (must cite graph node ids).
5. **Catalog** — merge status-valid Loom actions (`move_ready`, `move_running`, `move_blocked`, `move_done`, `request_review`, …) + playbook steps + cited candidates; dedupe by id.
6. **Jev choice** — pick `action_id` + confidence.
7. **Persist** — replace any existing pending suggestion for the task; emit WS.

### Loom action allowlist by status (examples)

- `todo` → `move_ready`, `move_blocked`
- `ready` → `move_running`, `move_blocked`
- `running` → `move_blocked`, `move_done`
- `blocked` → `move_ready`, `move_todo`
- `done` → `move_archived`

Accept of a Loom `move_*` action calls existing `update_agent_task`. Non-Loom actions mark accepted and surface prose only.

## 7. Keys & providers

- Jev: `TYPESAFE_API_KEY` env on daemon.
- Main model: user settings (BYOK); bootstrap from `DEEPSEEK_API_KEY` if settings empty.
- Default model id: `deepseek-chat` (DeepSeek OpenAI-compatible API at `https://api.deepseek.com`).
- GET `/api/agent/settings` returns `api_keys` as `{provider_id: "••••" + last4}` or null.

## 8. Worker / `loom-agent`

- Register in `known_agents` as always-available (no CLI detect required for dashboard agent).
- Runner: `loom` CLI subcommand or `python -m daemon.agent_run` that executes the task instruction in the worktree using `llm_client` (stdout mode), budget-aware where possible.
- Implement endpoint sets assignee to project-scoped `loom-agent` id pattern consistent with other agents.

## 9. Dashboard

- Project-level **Loom Agent** chat panel (optional `task_id` from selected card).
- Task card: suggestion chip (action, confidence, prose) + Accept / Dismiss / Implement.
- Settings: default model, API key, add provider (base URL + models).
- i18n: `en` + `ar`.

## 10. Guards

- Single-flight pending suggestion per task; auto-trigger cooldown (~30s).
- Accept re-reads task status; 409 if incompatible with action.
- Never log raw API keys.
- Drop candidates without graph citations.
- Missing main-model key → HTTP 400 with settings hint.

## 11. Testing

- Unit: jev/llm clients (mocked HTTP), catalog merge, empty-graph, single-flight.
- API: chat/suggest/accept/implement/settings with TestClient + injected registry.
- No live TypeSafe/DeepSeek calls in CI.

## 12. Out of scope

- Fully autonomous Implement without Accept
- Cloud multi-user key vault
- Replacing Claude/Codex CLI runners
