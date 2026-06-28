# Merge Target Branch Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a finished task merge into a user-chosen branch (local or remote), defaulting to the repo's current branch, performed via a temporary git worktree so the working checkout is never switched.

**Architecture:** Two new `daemon/worktree.py` helpers (`list_branches`, `merge_branch_into`) do the git work. `daemon/api.py` gains a `GET …/branches` endpoint and the existing merge endpoint accepts an optional `{target, remote}` body. The dashboard drawer renders a branch `<select>` next to the Merge button and passes the choice through `lib/api.ts`.

**Tech Stack:** Python 3 / FastAPI / pytest (daemon); Next.js 16 / React 19 / next-intl 4 / TypeScript (dashboard).

**Spec:** `docs/superpowers/specs/2026-06-28-merge-target-branch-selection-design.md`

**Pre-req for backend steps:** activate the venv once per shell — `source .venv/bin/activate`.

---

### Task 1: `worktree.list_branches`

**Files:**
- Modify: `daemon/worktree.py` (imports at top; new function after `merge_branch`, ~line 60)
- Test: `tests/test_worktree.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_worktree.py`:

```python
def test_list_branches_shape_and_exclusions(repo):
    _git(repo, "branch", "develop")
    _git(repo, "branch", "loom/task-zzz")
    data = worktree.list_branches(str(repo))
    assert data["current"] == "main"
    names = [b["name"] for b in data["branches"]]
    assert "main" in names
    assert "develop" in names
    assert "loom/task-zzz" not in names          # task branches excluded
    assert all(b["remote"] is False for b in data["branches"])  # no remotes here
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worktree.py::test_list_branches_shape_and_exclusions -v`
Expected: FAIL with `AttributeError: module 'daemon.worktree' has no attribute 'list_branches'`

- [ ] **Step 3: Add imports**

At the top of `daemon/worktree.py`, replace the import block:

```python
import subprocess
from pathlib import Path
```

with:

```python
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
```

- [ ] **Step 4: Implement `list_branches`**

Add after `merge_branch` (after line ~60) in `daemon/worktree.py`:

```python
def list_branches(repo_path: str) -> dict:
    """Local + remote branches for choosing a merge target.

    Returns ``{"current": str, "branches": [{"name": str, "remote": bool}]}``.
    Excludes ``loom/task-*`` branches and ``*/HEAD``, and omits a remote
    branch when a local branch of the same short name already exists.
    """
    current = current_branch(repo_path)
    local_proc = _run(repo_path, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    remote_proc = _run(repo_path, "for-each-ref", "--format=%(refname:short)", "refs/remotes")
    local = [n for n in local_proc.stdout.split("\n") if n and not n.startswith("loom/task-")]
    local_set = set(local)
    branches = [{"name": n, "remote": False} for n in local]
    for n in remote_proc.stdout.split("\n"):
        if not n or n.endswith("/HEAD"):
            continue
        short = n.split("/", 1)[1] if "/" in n else n
        if short in local_set:
            continue
        branches.append({"name": n, "remote": True})
    return {"current": current, "branches": branches}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_worktree.py::test_list_branches_shape_and_exclusions -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add daemon/worktree.py tests/test_worktree.py
git commit -m "feat(worktree): list_branches for merge-target selection"
```

---

### Task 2: `worktree.merge_branch_into`

**Files:**
- Modify: `daemon/worktree.py` (new function after `list_branches`)
- Test: `tests/test_worktree.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worktree.py`:

```python
def test_merge_branch_into_non_checked_out_branch(repo, tmp_path):
    # 'develop' exists but is not checked out (repo is on 'main').
    _git(repo, "branch", "develop")
    ws = tmp_path / "ws" / "task-m"
    worktree.create_worktree(str(repo), str(ws), "loom/task-m", base_ref="main")
    (ws / "feature.txt").write_text("work\n")
    worktree.commit_all(str(ws), "task m")

    ok, _out = worktree.merge_branch_into(str(repo), "loom/task-m", "develop")
    assert ok is True
    # Main checkout untouched: still on main, no feature.txt in its working tree.
    assert worktree.current_branch(str(repo)) == "main"
    assert not (repo / "feature.txt").exists()
    # 'develop' advanced and now contains the merged file.
    assert "work" in _git(repo, "show", "develop:feature.txt")
    # No throwaway merge worktree left behind.
    assert "loom-merge" not in _git(repo, "worktree", "list")
    worktree.remove_worktree(str(repo), str(ws))


def test_merge_branch_into_conflict_aborts(repo, tmp_path):
    # Put a conflicting change on 'develop'.
    _git(repo, "checkout", "-b", "develop")
    (repo / "README.md").write_text("develop change\n")
    _git(repo, "commit", "-am", "develop edit")
    _git(repo, "checkout", "main")
    # Task branch edits the same file differently.
    ws = tmp_path / "ws" / "task-c"
    worktree.create_worktree(str(repo), str(ws), "loom/task-c", base_ref="main")
    (ws / "README.md").write_text("task change\n")
    worktree.commit_all(str(ws), "task c")

    ok, out = worktree.merge_branch_into(str(repo), "loom/task-c", "develop")
    assert ok is False
    assert "conflict" in out.lower()
    # Clean state: still on main, working tree clean, no leftover worktree.
    assert worktree.current_branch(str(repo)) == "main"
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert "loom-merge" not in _git(repo, "worktree", "list")
    worktree.remove_worktree(str(repo), str(ws))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worktree.py -k merge_branch_into -v`
Expected: FAIL with `AttributeError: module 'daemon.worktree' has no attribute 'merge_branch_into'`

- [ ] **Step 3: Implement `merge_branch_into`**

Add after `list_branches` in `daemon/worktree.py`:

```python
def merge_branch_into(repo_path: str, source_branch: str, target: str,
                      *, target_is_remote: bool = False) -> tuple[bool, str]:
    """Merge ``source_branch`` into ``target`` (no fast-forward).

    If ``target`` is the repo's checked-out branch, merge in place (same as
    ``merge_branch``). Otherwise the merge runs inside a throwaway worktree so
    the user's working checkout is never switched. For a remote ``target``
    (e.g. ``origin/X``) a local branch ``X`` is created from it; nothing is
    pushed. On conflict the merge is aborted and ``(False, output)`` returned.
    """
    if not target_is_remote and target == current_branch(repo_path):
        return merge_branch(repo_path, source_branch)

    parent = tempfile.mkdtemp(prefix="loom-merge-")
    wt = os.path.join(parent, "wt")
    try:
        if target_is_remote:
            local_name = target.split("/", 1)[1]
            add = _run(repo_path, "worktree", "add", "-b", local_name, wt, target)
        else:
            add = _run(repo_path, "worktree", "add", wt, target)
        if add.returncode != 0:
            return False, (add.stdout + add.stderr).strip()
        proc = _run(wt, "merge", "--no-ff", "-m", f"Merge {source_branch}", source_branch)
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0:
            _run(wt, "merge", "--abort")
            return False, out
        return True, out
    finally:
        _run(repo_path, "worktree", "remove", "--force", wt)
        shutil.rmtree(parent, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worktree.py -k merge_branch_into -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/worktree.py tests/test_worktree.py
git commit -m "feat(worktree): merge_branch_into a chosen branch via temp worktree"
```

---

### Task 3: API — branches endpoint + target-aware merge

**Files:**
- Modify: `daemon/api.py:12` (import `Body`); merge endpoint at `daemon/api.py:813-828`; new branches endpoint nearby
- Test: `tests/test_api.py` (update 2 existing tests; add 3 new)

- [ ] **Step 1: Update/add the failing tests**

In `tests/test_api.py`, **replace** `test_task_merge_success` with:

```python
def test_task_merge_success(client, monkeypatch):
    import daemon.worktree as worktree_mod
    monkeypatch.setattr(worktree_mod, "current_branch", lambda repo: "main")
    monkeypatch.setattr(
        worktree_mod, "merge_branch_into",
        lambda repo, source, target, *, target_is_remote=False: (True, "Merged"),
    )
    res = client.post("/api/projects/noor/tasks",
                      json={"project": "noor", "title": "T", "instruction": "x"})
    task_id = res.json()["id"]
    client.patch(f"/api/projects/noor/tasks/{task_id}",
                 json={"workspace_path": "/tmp/ws/task-x"})
    res = client.post(f"/api/projects/noor/tasks/{task_id}/merge")
    assert res.status_code == 200
    assert res.json() == {"merged": True, "output": "Merged", "target": "main"}
```

**Replace** the final assertion of `test_task_merge_no_worktree` with:

```python
    assert res.json() == {"merged": False, "output": "No worktree assigned to this task", "target": ""}
```

**Append** three new tests to `tests/test_api.py`:

```python
def test_task_merge_with_target(client, monkeypatch):
    import daemon.worktree as worktree_mod
    captured = {}

    def fake_merge(repo, source, target, *, target_is_remote=False):
        captured["target"] = target
        captured["remote"] = target_is_remote
        return True, "ok"

    monkeypatch.setattr(worktree_mod, "merge_branch_into", fake_merge)
    res = client.post("/api/projects/noor/tasks",
                      json={"project": "noor", "title": "T", "instruction": "x"})
    task_id = res.json()["id"]
    client.patch(f"/api/projects/noor/tasks/{task_id}",
                 json={"workspace_path": "/tmp/ws/task-x"})
    res = client.post(f"/api/projects/noor/tasks/{task_id}/merge",
                      json={"target": "origin/dev", "remote": True})
    assert res.status_code == 200
    assert res.json() == {"merged": True, "output": "ok", "target": "origin/dev"}
    assert captured == {"target": "origin/dev", "remote": True}


def test_project_branches_success(client, monkeypatch):
    import daemon.worktree as worktree_mod
    fake = {"current": "main", "branches": [
        {"name": "main", "remote": False},
        {"name": "origin/dev", "remote": True},
    ]}
    monkeypatch.setattr(worktree_mod, "list_branches", lambda repo: fake)
    res = client.get("/api/projects/noor/branches")
    assert res.status_code == 200
    assert res.json() == fake


def test_project_branches_404_for_unknown_project(client):
    res = client.get("/api/projects/missing/branches")
    assert res.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -k "merge or branches" -v`
Expected: FAIL — `test_project_branches_*` 404/AttributeError, and merge tests fail on the missing `target` key / missing `merge_branch_into`.

- [ ] **Step 3: Import `Body`**

In `daemon/api.py:12`, change:

```python
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
```

to:

```python
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
```

- [ ] **Step 4: Replace the merge endpoint**

In `daemon/api.py`, replace the whole `task_merge` handler (lines ~813-828):

```python
@app.post("/api/projects/{project_id}/tasks/{task_id}/merge")
async def task_merge(project_id: str, task_id: str,
                     payload: dict | None = Body(default=None)):
    """Merge a task's worktree branch into a chosen target branch.

    Body is optional: ``{"target": "<branch>", "remote": <bool>}``. With no
    body, merges into the repo's current branch (backward compatible).
    """
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
    if not target:
        target = await asyncio.to_thread(_worktree.current_branch, repo)
        remote = False
    ok, output = await asyncio.to_thread(
        _worktree.merge_branch_into, repo, branch, target, target_is_remote=remote
    )
    return {"merged": ok, "output": output, "target": target}
```

- [ ] **Step 5: Add the branches endpoint**

In `daemon/api.py`, add immediately after the `task_merge` handler:

```python
@app.get("/api/projects/{project_id}/branches")
async def project_branches(project_id: str):
    """List local + remote branches the user can merge a task into."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = os.path.expanduser(project.project_path)
    return await asyncio.to_thread(_worktree.list_branches, repo)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_api.py -k "merge or branches" -v`
Expected: PASS (all merge + branches tests green)

- [ ] **Step 7: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat(api): branches endpoint and target-aware task merge"
```

---

### Task 4: Dashboard API client

**Files:**
- Modify: `dashboard/lib/api.ts:309-313` (mergeTask) and add `getBranches` after `getTaskDiff`

- [ ] **Step 1: Replace `mergeTask`**

In `dashboard/lib/api.ts`, replace the existing `mergeTask` (lines 309-313) with:

```ts
export async function mergeTask(
  projectId: string,
  taskId: string,
  target?: string,
  remote?: boolean,
): Promise<{ merged: boolean; output: string; target: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, remote }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getBranches(projectId: string): Promise<{
  current: string;
  branches: { name: string; remote: boolean }[];
}> {
  return fetchApi(`/api/projects/${projectId}/branches`);
}
```

- [ ] **Step 2: Type-check the change**

Run: `npm --prefix dashboard run lint`
Expected: PASS (no errors for `lib/api.ts`)

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat(dashboard): getBranches client + target arg on mergeTask"
```

---

### Task 5: i18n keys (en + ar)

**Files:**
- Modify: `dashboard/messages/en.json:237-238`
- Modify: `dashboard/messages/ar.json:237-238`

- [ ] **Step 1: Update English messages**

In `dashboard/messages/en.json`, replace lines 237-238:

```json
    "mergeOk": "Merged into the project branch.",
    "mergeConflict": "Merge failed — resolve conflicts manually.",
```

with:

```json
    "mergeConflict": "Merge failed — resolve conflicts manually.",
    "mergeInto": "Merge into",
    "mergedInto": "Merged into {branch}.",
```

- [ ] **Step 2: Update Arabic messages**

In `dashboard/messages/ar.json`, replace lines 237-238:

```json
    "mergeOk": "تم الدمج في فرع المشروع.",
    "mergeConflict": "فشل الدمج — قم بحل التعارضات يدويًا.",
```

with:

```json
    "mergeConflict": "فشل الدمج — قم بحل التعارضات يدويًا.",
    "mergeInto": "دمج في",
    "mergedInto": "تم الدمج في {branch}.",
```

- [ ] **Step 3: Verify both files are valid JSON**

Run: `node -e "require('./dashboard/messages/en.json'); require('./dashboard/messages/ar.json'); console.log('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Commit**

```bash
git add dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "i18n: add mergeInto/mergedInto, drop mergeOk"
```

---

### Task 6: Drawer branch selector

**Files:**
- Modify: `dashboard/components/task-detail-drawer.tsx` (import, state, effect, `handleMerge`, diff-header JSX)

- [ ] **Step 1: Import `getBranches`**

In the `@/lib/api` import block (lines 8-19), add `getBranches,` next to `mergeTask,`:

```ts
import {
  getTaskDiff,
  mergeTask,
  getBranches,
  updateAgentTask,
  getTaskProgress,
  startWorker,
  stopWorker,
  type AgentTask,
  type AgentInfo,
  type AgentTaskStatus,
  type TaskProgressItem,
} from "@/lib/api";
```

- [ ] **Step 2: Add branch state**

After `const [mergeMsg, setMergeMsg] = useState("");` (line 66), add:

```ts
  const [branches, setBranches] = useState<{ name: string; remote: boolean }[]>([]);
  const [target, setTarget] = useState("");
```

- [ ] **Step 3: Load branches for done/blocked tasks**

Immediately after the existing "Load diff" `useEffect` (ends at line 81), add a new effect:

```tsx
  // Load branch list + default target for completed/blocked tasks.
  useEffect(() => {
    if (!task) return;
    if (task.status === "done" || task.status === "blocked") {
      let cancelled = false;
      getBranches(projectId)
        .then((b) => {
          if (cancelled) return;
          setBranches(b.branches);
          setTarget(b.current);
        })
        .catch(() => {});
      return () => { cancelled = true; };
    }
  }, [task, projectId]);
```

- [ ] **Step 4: Pass the target through `handleMerge`**

Replace the body of `handleMerge` (lines 117-129):

```tsx
  async function handleMerge() {
    setMerging(true);
    setMergeMsg("");
    try {
      const sel = branches.find((b) => b.name === target);
      const res = await mergeTask(projectId, task!.id, target, sel?.remote ?? false);
      setMergeMsg(res.merged ? t("mergedInto", { branch: res.target }) : t("mergeConflict"));
      if (res.merged) onChanged();
    } catch {
      setMergeMsg(t("mergeConflict"));
    } finally {
      setMerging(false);
    }
  }
```

- [ ] **Step 5: Render the selector in the diff header**

Replace the diff-header row (lines 300-306, the `<div className="flex items-center justify-between mb-1">…</div>` containing the Merge button):

```tsx
            <div className="flex items-center justify-between mb-1">
              <label className="text-zinc-500">{t("diff")}</label>
              <div className="flex items-center gap-1">
                <select
                  aria-label={t("mergeInto")}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  disabled={merging}
                  className="bg-zinc-900 border border-zinc-700 rounded text-[11px] text-zinc-200 px-1 py-0.5 max-w-[160px]"
                >
                  {branches.map((b) => (
                    <option key={b.name} value={b.name}>{b.name}</option>
                  ))}
                </select>
                <Button size="sm" variant="outline" onClick={handleMerge} disabled={merging || !target}>
                  {merging ? <Loader2 className="w-3 h-3 animate-spin" /> : <GitMerge className="w-3 h-3" />}
                  <span className="ms-1">{t("merge")}</span>
                </Button>
              </div>
            </div>
```

- [ ] **Step 6: Lint + build**

Run: `npm --prefix dashboard run lint && npm --prefix dashboard run build`
Expected: lint clean; build succeeds (no missing-key/TS errors).

- [ ] **Step 7: Commit**

```bash
git add dashboard/components/task-detail-drawer.tsx
git commit -m "feat(dashboard): choose merge target branch in task drawer"
```

---

### Task 7: Full verification

- [ ] **Step 1: Run the daemon test suite**

Run: `source .venv/bin/activate && pytest tests/test_worktree.py tests/test_api.py -v`
Expected: all PASS (new + existing).

- [ ] **Step 2: Confirm the dashboard builds**

Run: `npm --prefix dashboard run build`
Expected: success.

- [ ] **Step 3: Manual smoke (with daemon + dashboard running)**

1. `loom --port 8472` and `npm --prefix dashboard run dev`.
2. Open a project with a done task → Tasks tab → open the task drawer.
3. The Changes section shows a branch dropdown (defaulting to the current branch) next to **Merge**.
4. Pick a different local branch, click **Merge**, confirm the message reads "Merged into <branch>" and the working checkout was not switched (`git -C <project> rev-parse --abbrev-ref HEAD` unchanged).
5. Verify the target branch advanced: `git -C <project> log --oneline -1 <branch>` shows the merge commit.

- [ ] **Step 4: Final commit (only if step 3 surfaced fixups)**

```bash
git add -A
git commit -m "fix: address merge-target smoke-test findings"
```

---

## Self-review notes

- **Spec coverage:** decisions 1-4 → Tasks 1 (list local+remote, dedup), 2 (temp-worktree method + remote-creates-local, no push), 3 (default = current branch via no-target fallback), 6 (default selection = `current`). i18n (Task 5), tests (Tasks 1-3). All spec sections map to a task.
- **Type consistency:** `merge_branch_into(repo, source, target, *, target_is_remote)` and the `{name, remote}` branch shape are used identically across worktree, api, tests, api.ts, and the drawer. Response shape `{merged, output, target}` is consistent in endpoint + test + client.
- **Backward compatibility:** no-body merge still works (Task 3 fallback); `merge_branch` retained and reused.
