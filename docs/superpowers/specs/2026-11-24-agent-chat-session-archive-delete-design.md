# Agent Chat Session Archive & Delete — Design

**Date:** 2026-11-24  
**Status:** Approved (conversation); pending written-spec review  
**Related:**
- `daemon/registry.py` — `agent_chats` / `agent_messages` tables and CRUD
- `daemon/models.py` — `AgentChatRecord`, `AgentChatSummary`
- `daemon/api.py` — `GET .../agent/chats`, `GET .../agent/chats/{id}/messages`, `POST .../agent/chat`
- `dashboard/components/loom-agent-chat.tsx` — Agent session sidebar + transcript
- `dashboard/lib/api.ts` — `listAgentChats`, `listAgentChatMessages`, `agentChat`

---

## 1. Summary

Let users **archive** and **delete** Agent chat sessions from the session sidebar.

- **Archive** is soft: hide from the default (active) list; recoverable via an Archived view; unarchive restores to active.
- **Delete** is hard: after confirmation, remove the chat row and all of its messages permanently.
- UI: **hover actions** on each session row (archive / delete; unarchive when viewing archived).

### Non-negotiable constraints

- Filesystem inbox + single-process daemon unchanged.
- Existing sessions with no `archived_at` remain active (NULL = not archived).
- Delete requires an explicit confirm step in the UI.
- Project scoping unchanged: cannot archive/delete a chat that belongs to another project (404).
- Existing test suite must stay green; add coverage for archive/unarchive/delete + list filter.
- Do not push or merge unless explicitly asked.

---

## 2. Decisions (from brainstorming)

| Fork | Decision |
|------|----------|
| Archive vs delete | Soft archive + separate hard delete (option 1) |
| UI affordance | Hover icons on each session row (option 1) |
| Delete safety | Confirm dialog before permanent delete (option 1) |
| Storage approach | `archived_at` nullable column on `agent_chats` (approach A) |
| Chat while archived | Allowed — archive only affects listing; sending a message does not auto-unarchive |
| Active session removed | If the open chat is archived or deleted, clear the open transcript and selection (empty / ready for new chat) |

---

## 3. Data model

### 3.1 Schema

Extend `agent_chats`:

| Column | Type | Notes |
|--------|------|--------|
| `archived_at` | `TEXT NULL` | ISO timestamp when archived; `NULL` = active |

Migration: on registry init, `PRAGMA table_info(agent_chats)`; if `archived_at` missing, `ALTER TABLE agent_chats ADD COLUMN archived_at TEXT`.

### 3.2 Models

- `AgentChatRecord` — add `archived_at: Optional[str] = None`
- `AgentChatSummary` — add `archived_at: Optional[str] = None` (clients treat non-null as archived; no separate `archived` bool)

Default list filter: only rows where `archived_at IS NULL`.

---

## 4. API

Base path: `/api/projects/{project_id}/agent/chats`

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/` | Query `task_id` (existing). New query `archived` = `0` (default) \| `1`. When `0`, return active chats; when `1`, return archived only. Same preview / ordering as today (`updated_at DESC`). |
| `POST` | `/{chat_id}/archive` | Set `archived_at = now` if chat exists and belongs to project. Idempotent if already archived. Returns updated summary. |
| `POST` | `/{chat_id}/unarchive` | Set `archived_at = NULL`. Idempotent if already active. Returns updated summary. |
| `DELETE` | `/{chat_id}` | Delete all `agent_messages` for `chat_id`, then delete `agent_chats` row. Success → **204 No Content**. 404 if missing / wrong project. |

Errors:

- Project missing → 404  
- Chat missing or `chat.project != project_id` → 404  

No WebSocket events required for v1 (sidebar refreshes after the mutating call). Optional later: `agent:chat_archived` / `agent:chat_deleted`.

---

## 5. Registry

New / extended methods:

- `list_agent_chats(..., archived: bool = False)` — filter `archived_at IS NULL` vs `IS NOT NULL`
- `archive_agent_chat(chat_id) -> AgentChatRecord | None`
- `unarchive_agent_chat(chat_id) -> AgentChatRecord | None`
- `delete_agent_chat(chat_id) -> bool` — delete messages then chat; return whether a row was deleted

`create_agent_chat` leaves `archived_at` NULL.  
`get_agent_chat` returns `archived_at` when present.

---

## 6. Dashboard UI

### 6.1 Session sidebar (`loom-agent-chat.tsx`)

- Default view: **Active** sessions (current list).
- Footer (or header control): toggle **Archived** — loads `listAgentChats(..., { archived: true })`. Show count when known/cheap; otherwise label only.
- Each row: on hover, show icon buttons:
  - Active view: **Archive**, **Delete**
  - Archived view: **Unarchive**, **Delete**
- Stop propagation so icon clicks do not select the session.
- **Delete** opens a confirm dialog: title/body explaining permanence; Confirm / Cancel. On confirm, call DELETE, refresh list; if deleted id was open, clear `chatId` + messages.
- **Archive / Unarchive**: call API, refresh list; if archived id was open while viewing Active, clear selection (same as design decision above).

### 6.2 API client (`lib/api.ts`)

- Extend `AgentChatSummary` with `archived_at: string | null`.
- `listAgentChats(projectId, taskId?, { archived?: boolean })`
- `archiveAgentChat(projectId, chatId)`
- `unarchiveAgentChat(projectId, chatId)`
- `deleteAgentChat(projectId, chatId)`

### 6.3 i18n

Add `en` + `ar` under `LoomAgent` (or existing agent chat namespace):  
`archiveSession`, `unarchiveSession`, `deleteSession`, `deleteSessionConfirmTitle`, `deleteSessionConfirmBody`, `confirmDelete`, `cancel`, `archivedSessions`, `activeSessions`, `noArchivedSessions`.

---

## 7. Out of scope (v1)

- Bulk archive/delete  
- Auto-unarchive on send  
- Renaming sessions  
- Soft-delete recycle bin beyond archive  
- WebSocket fan-out for session mutations  
- Changing message retention independently of chat delete  

---

## 8. Testing

- Registry: archive → list active excludes; list archived includes; unarchive restores; delete removes messages + chat.
- API: 404 wrong project; archive/unarchive idempotent; DELETE returns 204 then GET messages 404.
- Dashboard: not required for automated e2e in v1; manual check hover + confirm.

---

## 9. Implementation order

1. Schema migration + registry methods + model fields  
2. API routes + tests  
3. Dashboard API helpers + sidebar UI + i18n  
4. Sync App Support daemon copy if desktop install is in use (ops, not product code)
