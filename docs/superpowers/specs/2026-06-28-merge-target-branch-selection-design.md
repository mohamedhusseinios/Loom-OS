# Merge target branch selection — design

- **Date:** 2026-06-28
- **Status:** Approved (pending spec review)
- **Area:** Task execution → "Changes" / Merge (daemon + dashboard)

## Problem

When a dispatched task finishes, the task detail drawer shows the worktree
diff and a **Merge** button. Today the merge target is *implicit*:
`worktree.merge_branch(repo_path, branch)` runs
`git merge --no-ff loom/task-<id>` into **whatever branch is currently checked
out** in the project repo. The UI can only say "Merged into the project
branch" — the user has no way to direct the work into a different branch
(e.g. `develop`, a release branch, or a branch that only exists on the remote).

**Goal:** let the user choose which branch the task is merged into, from the
Merge control in the task drawer.

## Decisions (locked)

1. **Branch list scope:** offer **local + remote** branches.
2. **Default selection:** the repo's **current (checked-out)** branch — preserves
   today's behavior as the default.
3. **Merge method:** when the chosen target is not the checked-out branch, merge
   inside a **temporary git worktree** so the user's working checkout is never
   switched or touched.
4. **Remote-merge semantics:** merging into `origin/X` (when no local `X` exists)
   **creates a local `X` from the remote ref, merges into it, and stops — no
   automatic `git push`.** The user pushes when ready.

## Non-goals

- No `git push` / remote mutation (see decision 4).
- No new-branch-by-typing-a-name field (only existing local/remote branches).
- No change to how task worktrees are created or how the diff is computed.
- No change to the 7-state task lifecycle.

## Design

### Backend — `daemon/worktree.py`

Two new helpers; the existing `merge_branch` is retained and reused.

#### `list_branches(repo_path: str) -> dict`

Returns the data the dropdown needs:

```json
{ "current": "main",
  "branches": [ { "name": "main", "remote": false },
                { "name": "develop", "remote": false },
                { "name": "origin/release-1.2", "remote": true } ] }
```

Rules:
- Local names from `git for-each-ref --format=%(refname:short) refs/heads`.
- Remote names from `git for-each-ref --format=%(refname:short) refs/remotes`.
- Exclude `loom/task-*` branches (a task never merges into another task branch).
- Skip `origin/HEAD`.
- **De-duplicate:** a remote `origin/X` is omitted if a local `X` already exists.
- `current` comes from the existing `current_branch(repo_path)` helper.

#### `merge_branch_into(repo_path, source_branch, target, *, target_is_remote=False) -> tuple[bool, str]`

- If `not target_is_remote and target == current_branch(repo_path)`:
  delegate to the existing `merge_branch(repo_path, source_branch)` — the
  in-place path (git cannot check out the same branch in a second worktree, and
  this preserves today's exact behavior).
- Otherwise, perform the merge in a throwaway worktree:
  1. `parent = tempfile.mkdtemp(prefix="loom-merge-")`; `wt = parent/"wt"`.
  2. Add the worktree on the target:
     - local target: `git -C repo worktree add <wt> <target>`
     - remote target: `git -C repo worktree add -b <X> <wt> <target>`
       where `X = target.split("/", 1)[1]` (e.g. `origin/release-1.2` → `release-1.2`).
       Creating local `X` from the remote ref is the remote-merge semantic.
  3. `git -C <wt> merge --no-ff -m "Merge <source_branch>" <source_branch>`.
  4. On non-zero return: `git -C <wt> merge --abort`, return `(False, output)`.
  5. On success: return `(True, output)`. The merge commit advances the real
     `target` branch ref (a worktree commit advances its checked-out branch).
  6. **Always** clean up in a `finally`: `git -C repo worktree remove --force <wt>`
     and `shutil.rmtree(parent, ignore_errors=True)`.

The user's main checkout is never switched; conflicts are isolated to the
throwaway worktree and aborted, leaving no mess behind.

### Backend — `daemon/api.py`

#### New: `GET /api/projects/{project_id}/branches`

```python
@app.get("/api/projects/{project_id}/branches")
async def project_branches(project_id: str):
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = os.path.expanduser(project.project_path)
    return await asyncio.to_thread(_worktree.list_branches, repo)
```

#### Changed: `POST /api/projects/{project_id}/tasks/{task_id}/merge`

Accept an **optional** JSON body so existing no-body callers/tests keep working
(`from fastapi import Body`):

```python
@app.post("/api/projects/{project_id}/tasks/{task_id}/merge")
async def task_merge(project_id: str, task_id: str,
                     payload: dict | None = Body(default=None)):
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not record.workspace_path:
        return {"merged": False, "output": "No worktree assigned to this task",
                "target": ""}
    repo = os.path.expanduser(project.project_path)
    branch = f"loom/task-{task_id}"
    target = (payload or {}).get("target")
    remote = bool((payload or {}).get("remote", False))
    if not target:                       # backward-compatible default
        target = await asyncio.to_thread(_worktree.current_branch, repo)
        remote = False
    ok, output = await asyncio.to_thread(
        _worktree.merge_branch_into, repo, branch, target, target_is_remote=remote
    )
    return {"merged": ok, "output": output, "target": target}
```

### Frontend — `dashboard/lib/api.ts`

- New client:
  ```ts
  export async function getBranches(projectId: string): Promise<{
    current: string; branches: { name: string; remote: boolean }[];
  }> {
    return fetchApi(`/api/projects/${projectId}/branches`);
  }
  ```
- `mergeTask` gains target args and sends a JSON body; return type gains `target`:
  ```ts
  export async function mergeTask(
    projectId: string, taskId: string, target?: string, remote?: boolean,
  ): Promise<{ merged: boolean; output: string; target: string }> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, remote }),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  }
  ```

### Frontend — `dashboard/components/task-detail-drawer.tsx`

- New state: `branches`, `target` (selected name), derived `remote` flag.
- Load branches via `getBranches` when the drawer shows a done/blocked task with
  a diff; initialize `target` to the returned `current`.
- Render a compact branch `<select>` immediately to the left of the Merge button,
  inside the existing diff-header `flex` row. Selecting an entry updates `target`.
- `handleMerge` resolves the selected branch's `remote` flag and calls
  `mergeTask(projectId, task.id, target, remote)`; on success show
  `t("mergedInto", { branch: res.target })`.
- RTL is preserved (the row already uses logical `ms-*` spacing).

### i18n

Add keys to **both** `messages/en.json` and `messages/ar.json` under the task
drawer namespace:

- `mergeInto` — accessible label / placeholder for the selector
  (en: "Merge into", ar: "دمج في").
- `mergedInto` — success message with interpolation
  (en: "Merged into {branch}", ar: "تم الدمج في {branch}").

Existing `merge` and `mergeConflict` keys are kept. `mergeOk` is superseded by
`mergedInto`: remove its usage in the component and delete the `mergeOk` key
from both locale files.

## Tests

### `tests/test_worktree.py`

- `list_branches` returns `current`, includes local branches, excludes
  `loom/task-*`, and de-duplicates a remote that has a local counterpart.
- Merge a source branch into a **non-checked-out** local branch via the
  temp-worktree path: target branch advances, the main checkout stays on its
  original branch and is clean, and no `loom-merge-*` worktree remains.
- Conflict case: `merge_branch_into` returns `(False, output)`, the merge is
  aborted, and no leftover worktree/temp dir remains.

### `tests/test_api.py`

- `GET …/branches`: success shape + 404 for unknown project.
- `POST …/merge` with an explicit `{"target": ...}` body merges into that target
  and echoes it in the response.
- **Update** the existing `test_task_merge_success` (and related merge tests):
  they currently monkeypatch `_worktree.merge_branch`; after this change the
  endpoint calls `_worktree.merge_branch_into`, so the patch target must change
  (and `current_branch` may need patching for the no-body default path). The
  no-body POST must still succeed.

## Backward compatibility

- `POST …/merge` with no body behaves exactly as today (merge into the current
  branch); the response simply gains a `target` field.
- `worktree.merge_branch` is unchanged and still used for the in-place path.
