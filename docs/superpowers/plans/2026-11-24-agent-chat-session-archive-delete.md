# Agent Chat Session Archive & Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users soft-archive Agent chat sessions (hide / restore) and permanently delete them (with confirm) from the Agent session sidebar.

**Architecture:** Add nullable `archived_at` on `agent_chats`. Registry filters lists and provides archive / unarchive / delete. REST endpoints under `/api/projects/{id}/agent/chats`. Dashboard sidebar gains Active/Archived toggle, hover Archive/Delete/Unarchive icons, and a delete confirm dialog.

**Tech Stack:** Python FastAPI + aiosqlite (`daemon/`), Next.js 16 + React 19 dashboard, next-intl (`en`/`ar`), existing `Button` + lucide icons.

**Spec:** `docs/superpowers/specs/2026-11-24-agent-chat-session-archive-delete-design.md`

## Global Constraints

- Soft archive via `archived_at TEXT NULL` (NULL = active); hard delete cascades messages
- `GET .../chats` defaults to active only; `?archived=1` returns archived only
- `DELETE .../chats/{id}` → **204 No Content**; wrong project / missing chat → **404**
- Archive/unarchive are idempotent; chatting an archived session is allowed and does **not** auto-unarchive
- If the open session is archived (while viewing Active) or deleted, clear `chatId` + messages in the UI
- Hover icons on session rows; delete requires confirm UI
- Every new UI string in both `dashboard/messages/en.json` and `dashboard/messages/ar.json` under `LoomAgent`
- Filesystem inbox + single-process daemon unchanged
- Do not push / open / merge without explicit user approval
- Keep existing pytest suite green; add registry + API tests for this feature

## File map

| Path | Responsibility |
|------|----------------|
| `daemon/models.py` | `archived_at` on `AgentChatRecord` / `AgentChatSummary` |
| `daemon/registry.py` | Schema migrate; list filter; archive / unarchive / delete; summary helper |
| `daemon/api.py` | Query `archived`; POST archive/unarchive; DELETE chat |
| `tests/test_agent_orchestrator_registry.py` | Registry archive/list/delete tests |
| `tests/test_agent_api.py` | HTTP archive/unarchive/delete + list filter |
| `dashboard/lib/api.ts` | Types + client helpers |
| `dashboard/components/loom-agent-chat.tsx` | Sidebar toggle, hover actions, confirm |
| `dashboard/messages/en.json` / `ar.json` | i18n strings |

---

### Task 1: Models + registry schema & methods

**Files:**
- Modify: `daemon/models.py` (`AgentChatRecord`, `AgentChatSummary`)
- Modify: `daemon/registry.py` (init migrate + chat CRUD)
- Test: `tests/test_agent_orchestrator_registry.py`

**Interfaces:**
- Consumes: existing `create_agent_chat`, `add_agent_message`, `list_agent_messages`
- Produces:
  - `AgentChatRecord.archived_at: Optional[str] = None`
  - `AgentChatSummary.archived_at: Optional[str] = None`
  - `list_agent_chats(self, project: str, task_id: str | None = None, limit: int = 50, archived: bool = False) -> list[AgentChatSummary]`
  - `archive_agent_chat(self, chat_id: str) -> AgentChatRecord | None`
  - `unarchive_agent_chat(self, chat_id: str) -> AgentChatRecord | None`
  - `delete_agent_chat(self, chat_id: str) -> bool`
  - `agent_chat_summary(self, chat_id: str) -> AgentChatSummary | None` (preview helper for API responses)

- [ ] **Step 1: Write the failing registry tests**

Append to `tests/test_agent_orchestrator_registry.py`:

```python
@pytest.mark.asyncio
async def test_archive_unarchive_filters_lists(reg):
    active = await reg.create_agent_chat("proj")
    await reg.add_agent_message(active.id, "user", "keep me")
    other = await reg.create_agent_chat("proj")
    await reg.add_agent_message(other.id, "user", "archive me")

    archived = await reg.archive_agent_chat(other.id)
    assert archived is not None
    assert archived.archived_at is not None
    again = await reg.archive_agent_chat(other.id)
    assert again is not None and again.archived_at == archived.archived_at

    active_list = await reg.list_agent_chats("proj", archived=False)
    assert [c.id for c in active_list] == [active.id]
    assert active_list[0].archived_at is None

    archived_list = await reg.list_agent_chats("proj", archived=True)
    assert [c.id for c in archived_list] == [other.id]
    assert archived_list[0].archived_at is not None
    assert archived_list[0].preview == "archive me"

    restored = await reg.unarchive_agent_chat(other.id)
    assert restored is not None and restored.archived_at is None
    assert [c.id for c in await reg.list_agent_chats("proj", archived=False)] == [
        other.id, active.id,
    ] or set(c.id for c in await reg.list_agent_chats("proj", archived=False)) == {
        other.id, active.id,
    }


@pytest.mark.asyncio
async def test_delete_agent_chat_removes_messages(reg):
    chat = await reg.create_agent_chat("proj")
    await reg.add_agent_message(chat.id, "user", "bye")
    assert await reg.delete_agent_chat(chat.id) is True
    assert await reg.get_agent_chat(chat.id) is None
    assert await reg.list_agent_messages(chat.id) == []
    assert await reg.delete_agent_chat(chat.id) is False
```

(Prefer asserting active list membership with a set if `updated_at` ordering after unarchive is ambiguous.)

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os
# use App Support or repo venv python that has pytest
PYTHONPATH=. python -m pytest tests/test_agent_orchestrator_registry.py::test_archive_unarchive_filters_lists tests/test_agent_orchestrator_registry.py::test_delete_agent_chat_removes_messages -v
```

Expected: FAIL (missing methods / `archived` kwarg / `archived_at` field).

- [ ] **Step 3: Update models**

In `daemon/models.py`, add `archived_at: Optional[str] = None` to both `AgentChatRecord` and `AgentChatSummary`.

- [ ] **Step 4: Migrate schema + implement registry methods**

In `daemon/registry.py` immediately after `CREATE TABLE IF NOT EXISTS agent_chats (...)`:

```python
cursor = await self.db.execute("PRAGMA table_info(agent_chats)")
chat_cols = [r[1] for r in await cursor.fetchall()]
if "archived_at" not in chat_cols:
    await self.db.execute(
        "ALTER TABLE agent_chats ADD COLUMN archived_at TEXT"
    )
```

Update `get_agent_chat` to pass `archived_at=row["archived_at"] if "archived_at" in row.keys() else None`.

Update `list_agent_chats` signature to add `archived: bool = False`. Extend `where`:

```python
arch_clause = "c.archived_at IS NOT NULL" if archived else "c.archived_at IS NULL"
# append with AND to existing where
where = f"{where} AND {arch_clause}"
```

Select `c.archived_at` in the SELECT list and pass into `AgentChatSummary(...)`.

Implement:

```python
async def archive_agent_chat(self, chat_id: str) -> AgentChatRecord | None:
    chat = await self.get_agent_chat(chat_id)
    if chat is None:
        return None
    if chat.archived_at is None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE agent_chats SET archived_at = ? WHERE id = ?",
            (now, chat_id),
        )
        await self.db.commit()
        return await self.get_agent_chat(chat_id)
    return chat

async def unarchive_agent_chat(self, chat_id: str) -> AgentChatRecord | None:
    chat = await self.get_agent_chat(chat_id)
    if chat is None:
        return None
    if chat.archived_at is not None:
        await self.db.execute(
            "UPDATE agent_chats SET archived_at = NULL WHERE id = ?",
            (chat_id,),
        )
        await self.db.commit()
        return await self.get_agent_chat(chat_id)
    return chat

async def delete_agent_chat(self, chat_id: str) -> bool:
    chat = await self.get_agent_chat(chat_id)
    if chat is None:
        return False
    await self.db.execute("DELETE FROM agent_messages WHERE chat_id = ?", (chat_id,))
    await self.db.execute("DELETE FROM agent_chats WHERE id = ?", (chat_id,))
    await self.db.commit()
    return True

async def agent_chat_summary(self, chat_id: str) -> AgentChatSummary | None:
    chat = await self.get_agent_chat(chat_id)
    if chat is None:
        return None
    cursor = await self.db.execute(
        "SELECT content FROM agent_messages WHERE chat_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (chat_id,),
    )
    row = await cursor.fetchone()
    preview = ((row["content"] if row else "") or "")[:120]
    return AgentChatSummary(
        id=chat.id, project=chat.project, task_id=chat.task_id,
        created_at=chat.created_at, updated_at=chat.updated_at,
        preview=preview, archived_at=chat.archived_at,
    )
```

- [ ] **Step 5: Run registry tests**

```bash
PYTHONPATH=. python -m pytest tests/test_agent_orchestrator_registry.py -v --tb=short
```

Expected: PASS (including existing chat tests).

- [ ] **Step 6: Commit**

```bash
git add daemon/models.py daemon/registry.py tests/test_agent_orchestrator_registry.py
git commit -m "$(cat <<'EOF'
feat(agent): add archived_at and chat archive/delete registry APIs

EOF
)"
```

---

### Task 2: REST endpoints + API tests

**Files:**
- Modify: `daemon/api.py` (list_agent_chats + new routes near existing agent chat handlers ~1072)
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Consumes: registry methods from Task 1
- Produces:
  - `GET /api/projects/{project_id}/agent/chats?archived=0|1&task_id=`
  - `POST /api/projects/{project_id}/agent/chats/{chat_id}/archive` → summary JSON
  - `POST /api/projects/{project_id}/agent/chats/{chat_id}/unarchive` → summary JSON
  - `DELETE /api/projects/{project_id}/agent/chats/{chat_id}` → 204

- [ ] **Step 1: Write the failing API tests**

Append to `tests/test_agent_api.py`:

```python
async def test_archive_unarchive_delete_agent_chat(client):
    import daemon.api as api_module
    from fastapi import Response

    chat = await api_module.registry.create_agent_chat("noor", task_id=None)
    await api_module.registry.add_agent_message(chat.id, "user", "secret")

    arch = client.post(f"/api/projects/noor/agent/chats/{chat.id}/archive")
    assert arch.status_code == 200
    assert arch.json()["archived_at"] is not None
    assert arch.json()["id"] == chat.id

    # idempotent
    arch2 = client.post(f"/api/projects/noor/agent/chats/{chat.id}/archive")
    assert arch2.status_code == 200
    assert arch2.json()["archived_at"] == arch.json()["archived_at"]

    active = client.get("/api/projects/noor/agent/chats")
    assert chat.id not in [c["id"] for c in active.json()["chats"]]

    archived = client.get("/api/projects/noor/agent/chats", params={"archived": 1})
    assert [c["id"] for c in archived.json()["chats"]] == [chat.id]

    un = client.post(f"/api/projects/noor/agent/chats/{chat.id}/unarchive")
    assert un.status_code == 200
    assert un.json()["archived_at"] is None
    assert chat.id in [c["id"] for c in client.get("/api/projects/noor/agent/chats").json()["chats"]]

    wrong = client.post(f"/api/projects/missing/agent/chats/{chat.id}/archive")
    assert wrong.status_code == 404

    deleted = client.delete(f"/api/projects/noor/agent/chats/{chat.id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/noor/agent/chats/{chat.id}/messages").status_code == 404
    assert client.delete(f"/api/projects/noor/agent/chats/{chat.id}").status_code == 404
```

Remove the unused `Response` import from the test if unused.

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. python -m pytest tests/test_agent_api.py::test_archive_unarchive_delete_agent_chat -v
```

Expected: FAIL (404 on archive route or missing query behavior).

- [ ] **Step 3: Implement API routes**

Update `list_agent_chats` handler:

```python
@app.get("/api/projects/{project_id}/agent/chats")
async def list_agent_chats(
    project_id: str,
    task_id: Optional[str] = None,
    archived: int = 0,
):
    project = await registry.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    chats = await registry.list_agent_chats(
        project_id, task_id=task_id, archived=bool(archived),
    )
    return {"chats": [c.model_dump() for c in chats]}
```

Add helper + routes after `list_agent_chat_messages`:

```python
async def _require_project_chat(project_id: str, chat_id: str):
    project = await registry.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    chat = await registry.get_agent_chat(chat_id)
    if chat is None or chat.project != project_id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.post("/api/projects/{project_id}/agent/chats/{chat_id}/archive")
async def archive_agent_chat(project_id: str, chat_id: str):
    await _require_project_chat(project_id, chat_id)
    await registry.archive_agent_chat(chat_id)
    summary = await registry.agent_chat_summary(chat_id)
    return summary.model_dump()


@app.post("/api/projects/{project_id}/agent/chats/{chat_id}/unarchive")
async def unarchive_agent_chat(project_id: str, chat_id: str):
    await _require_project_chat(project_id, chat_id)
    await registry.unarchive_agent_chat(chat_id)
    summary = await registry.agent_chat_summary(chat_id)
    return summary.model_dump()


@app.delete("/api/projects/{project_id}/agent/chats/{chat_id}", status_code=204)
async def delete_agent_chat(project_id: str, chat_id: str):
    await _require_project_chat(project_id, chat_id)
    await registry.delete_agent_chat(chat_id)
    return Response(status_code=204)
```

Ensure `Response` is imported from `fastapi` / `starlette.responses` (match existing `api.py` imports).

- [ ] **Step 4: Run API tests**

```bash
PYTHONPATH=. python -m pytest tests/test_agent_api.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_agent_api.py
git commit -m "$(cat <<'EOF'
feat(agent): expose chat archive, unarchive, and delete HTTP endpoints

EOF
)"
```

---

### Task 3: Dashboard API client + i18n + sidebar UI

**Files:**
- Modify: `dashboard/lib/api.ts`
- Modify: `dashboard/messages/en.json` (`LoomAgent` keys)
- Modify: `dashboard/messages/ar.json` (`LoomAgent` keys)
- Modify: `dashboard/components/loom-agent-chat.tsx`

**Interfaces:**
- Consumes: Task 2 HTTP API
- Produces:
  - `listAgentChats(projectId, taskId?, opts?: { archived?: boolean })`
  - `archiveAgentChat(projectId, chatId): Promise<AgentChatSummary>`
  - `unarchiveAgentChat(projectId, chatId): Promise<AgentChatSummary>`
  - `deleteAgentChat(projectId, chatId): Promise<void>`

- [ ] **Step 1: Extend `api.ts`**

```typescript
export interface AgentChatSummary {
  id: string;
  project: string;
  task_id: string | null;
  created_at: string;
  updated_at: string;
  preview: string;
  archived_at: string | null;
}

export async function listAgentChats(
  projectId: string,
  taskId?: string | null,
  opts?: { archived?: boolean },
): Promise<AgentChatSummary[]> {
  const params = new URLSearchParams();
  if (taskId) params.set("task_id", taskId);
  if (opts?.archived) params.set("archived", "1");
  const qs = params.toString() ? `?${params.toString()}` : "";
  const data = await fetchApi<{ chats: AgentChatSummary[] }>(
    `/api/projects/${projectId}/agent/chats${qs}`,
  );
  return data.chats;
}

export async function archiveAgentChat(projectId: string, chatId: string): Promise<AgentChatSummary> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/agent/chats/${chatId}/archive`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(detail.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function unarchiveAgentChat(projectId: string, chatId: string): Promise<AgentChatSummary> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/agent/chats/${chatId}/unarchive`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(detail.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function deleteAgentChat(projectId: string, chatId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/agent/chats/${chatId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(detail.detail || `API error: ${res.status}`);
  }
}
```

- [ ] **Step 2: Add i18n strings**

In `dashboard/messages/en.json` under `LoomAgent` (near `sessions` / `newChat`):

```json
"archiveSession": "Archive",
"unarchiveSession": "Unarchive",
"deleteSession": "Delete",
"deleteSessionConfirmTitle": "Delete this session?",
"deleteSessionConfirmBody": "This permanently removes the conversation and cannot be undone.",
"confirmDelete": "Delete",
"cancel": "Cancel",
"archivedSessions": "Archived",
"activeSessions": "Active",
"noArchivedSessions": "No archived sessions"
```

In `dashboard/messages/ar.json` under `LoomAgent`:

```json
"archiveSession": "أرشفة",
"unarchiveSession": "إلغاء الأرشفة",
"deleteSession": "حذف",
"deleteSessionConfirmTitle": "حذف هذه الجلسة؟",
"deleteSessionConfirmBody": "سيُحذف الحوار نهائياً ولا يمكن التراجع.",
"confirmDelete": "حذف",
"cancel": "إلغاء",
"archivedSessions": "المؤرشفة",
"activeSessions": "النشطة",
"noArchivedSessions": "لا جلسات مؤرشفة"
```

- [ ] **Step 3: Update `loom-agent-chat.tsx`**

Imports: add `Archive`, `ArchiveRestore`, `Trash2` from `lucide-react`; import `archiveAgentChat`, `unarchiveAgentChat`, `deleteAgentChat`.

State:

```typescript
const [showArchived, setShowArchived] = useState(false);
const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
```

Update `refreshSessions` to pass `{ archived: showArchived }`:

```typescript
const chats = await listAgentChats(projectId, taskId || undefined, { archived: showArchived });
```

`useEffect` that depends on `showArchived` should call `refreshSessions` when the toggle changes.

Clear open chat helper:

```typescript
function clearOpenChat() {
  setChatId(undefined);
  setMessages([]);
}
```

Handlers:

```typescript
async function onArchive(id: string) {
  try {
    await archiveAgentChat(projectId, id);
    if (chatId === id) clearOpenChat();
    await refreshSessions();
  } catch (e) {
    setError(e instanceof Error ? e.message : String(e));
  }
}

async function onUnarchive(id: string) {
  try {
    await unarchiveAgentChat(projectId, id);
    await refreshSessions();
  } catch (e) {
    setError(e instanceof Error ? e.message : String(e));
  }
}

async function onConfirmDelete() {
  if (!pendingDeleteId) return;
  const id = pendingDeleteId;
  setPendingDeleteId(null);
  try {
    await deleteAgentChat(projectId, id);
    if (chatId === id) clearOpenChat();
    await refreshSessions();
  } catch (e) {
    setError(e instanceof Error ? e.message : String(e));
  }
}
```

Session row UI (replace the plain `<button>` map body): use a relative wrapper; main click still `loadSession`; hover reveals icon buttons with `e.stopPropagation()` / `type="button"`. Active view: Archive + Delete. Archived view: Unarchive + Delete. Delete sets `pendingDeleteId`.

Empty copy: when `showArchived`, use `t("noArchivedSessions")` instead of `t("noSessions")`.

Footer toggle below the list:

```tsx
<button
  type="button"
  className="border-t border-zinc-800 px-2 py-1.5 text-[11px] text-zinc-500 hover:text-zinc-200"
  onClick={() => setShowArchived((v) => !v)}
>
  {showArchived ? t("activeSessions") : t("archivedSessions")}
</button>
```

Delete confirm: when `pendingDeleteId` set, show a small overlay/panel (fixed or absolute in the chat panel) with title `deleteSessionConfirmTitle`, body `deleteSessionConfirmBody`, Cancel → clear pending, Confirm → `onConfirmDelete`. Prefer an in-component panel with existing `Button` styles (no new AlertDialog package).

- [ ] **Step 4: Manual smoke (dashboard)**

With daemon on `:8472` and `cd dashboard && npm run dev`:

1. Open Agent tab → create/send a message in a session  
2. Hover → Archive → session leaves Active list; open transcript clears if it was selected  
3. Toggle Archived → session appears; Unarchive restores  
4. Delete → confirm → session gone; messages 404  

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/components/loom-agent-chat.tsx dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "$(cat <<'EOF'
feat(dashboard): archive and delete Agent chat sessions from the sidebar

EOF
)"
```

---

### Task 4: Spec status + ops note

**Files:**
- Modify: `docs/superpowers/specs/2026-11-24-agent-chat-session-archive-delete-design.md` (status line)

- [ ] **Step 1: Mark spec approved**

Set status to: `Approved (written-spec review 2026-11-24)`.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-11-24-agent-chat-session-archive-delete-design.md
git commit -m "$(cat <<'EOF'
docs: mark agent chat archive/delete spec as approved

EOF
)"
```

- [ ] **Step 3 (ops, not committed unless needed):** If desktop uses App Support install, copy updated `daemon/models.py`, `daemon/registry.py`, `daemon/api.py` into `~/Library/Application Support/LoomCodingAgent/app/` and restart `loom` on `:8472`.

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| `archived_at` column + migrate | Task 1 |
| Soft archive / unarchive / hard delete | Task 1–2 |
| List `?archived=0\|1` | Task 2 |
| DELETE 204 + project 404 | Task 2 |
| Hover archive/delete/unarchive | Task 3 |
| Confirm before delete | Task 3 |
| Active ↔ Archived toggle | Task 3 |
| Clear open chat on archive (active view) / delete | Task 3 |
| en + ar strings | Task 3 |
| Registry + API tests | Task 1–2 |
| No auto-unarchive on send | (no code change; chat path untouched) |
| Out of scope (bulk, WS, rename) | Not planned |

No TBD/placeholder steps remain. Method names are consistent across tasks (`archive_agent_chat`, `agent_chat_summary`, `archiveAgentChat`).
