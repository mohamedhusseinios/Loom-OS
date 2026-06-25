# Dashboard Features — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add project CRUD, interactive graph explorer (Cytoscape.js), and agent management with wiring + dispatch to the Agentic OS dashboard.

**Architecture:** API-First — extend daemon with new FastAPI endpoints (project CRUD, graph topology, agent dispatch), then build dashboard components that consume them. Graph visualization uses Cytoscape.js with force-directed layout. Agent dispatch extends the filesystem inbox protocol with `task-*.json` files.

**Tech Stack:** Python (FastAPI, Pydantic, aiosqlite, Graphify), TypeScript (Next.js 16, React 19, Shadcn UI, Tailwind CSS, Cytoscape.js)

---

## Phase 1: Project CRUD

### Task 1: Add project CRUD models to daemon

**Objective:** Add Pydantic models for project creation, deletion, and disk discovery

**Files:**
- Modify: `daemon/models.py`

**Step 1: Add models**

```python
# Add after existing models in daemon/models.py

class ProjectCreatePayload(BaseModel):
    name: str
    path: str

class ProjectDeleteResult(BaseModel):
    deleted: bool

class DiscoverResult(BaseModel):
    directories: list[dict]  # [{name, path, has_git}]
```

**Step 2: Run type check**

Run: `python -c "from daemon.models import ProjectCreatePayload, ProjectDeleteResult, DiscoverResult; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add daemon/models.py
git commit -m "feat: add project CRUD and discovery models"
```

---

### Task 2: Add project CRUD methods to registry

**Objective:** Add `create_project`, `delete_project` methods to AgentRegistry

**Files:**
- Modify: `daemon/registry.py`

**Step 1: Add methods**

```python
# Add to AgentRegistry class in daemon/registry.py

async def create_project(self, project_id: str, project_name: str, project_path: str) -> ProjectInfo:
    await self.db.execute(
        "INSERT INTO projects (project_id, project_name, project_path) VALUES (?, ?, ?)",
        (project_id, project_name, project_path),
    )
    await self.db.commit()
    return await self.get_project(project_id)

async def delete_project(self, project_id: str) -> bool:
    cursor = await self.db.execute(
        "DELETE FROM projects WHERE project_id = ?", (project_id,)
    )
    await self.db.commit()
    return cursor.rowcount > 0
```

**Step 2: Write failing test**

```python
# tests/test_registry.py — add these tests

@pytest.mark.asyncio
async def test_create_and_delete_project():
    registry = AgentRegistry(db_path=":memory:")
    await registry.initialize()
    project = await registry.create_project("test-proj", "Test Project", "/tmp/test")
    assert project.project_id == "test-proj"
    assert project.project_name == "Test Project"
    
    deleted = await registry.delete_project("test-proj")
    assert deleted is True
    
    gone = await registry.get_project("test-proj")
    assert gone is None
    
    await registry.close()

@pytest.mark.asyncio
async def test_delete_nonexistent_project():
    registry = AgentRegistry(db_path=":memory:")
    await registry.initialize()
    deleted = await registry.delete_project("nonexistent")
    assert deleted is False
    await registry.close()
```

**Step 3: Run test to verify fail**

Run: `pytest tests/test_registry.py::test_create_and_delete_project tests/test_registry.py::test_delete_nonexistent_project -v`
Expected: FAIL — methods not found

**Step 4: Run test to verify pass**

Run: `pytest tests/test_registry.py::test_create_and_delete_project tests/test_registry.py::test_delete_nonexistent_project -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add daemon/registry.py tests/test_registry.py
git commit -m "feat: add create/delete project methods to registry"
```

---

### Task 3: Add project CRUD API endpoints

**Objective:** Add `POST /api/projects`, `DELETE /api/projects/:id`, `GET /api/discover` endpoints

**Files:**
- Modify: `daemon/api.py`

**Step 1: Add endpoints in daemon/api.py**

```python
from daemon.models import ProjectCreatePayload, ProjectDeleteResult, DiscoverResult

@app.post("/api/projects", status_code=201)
async def create_project(payload: ProjectCreatePayload):
    """Create a new tracked project."""
    import os
    path = os.path.expanduser(payload.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")
    project = await registry.create_project(payload.name, payload.name, path)
    # Emit WS event
    if router:
        await router._emit_event("project:created", payload.name, {"project_id": payload.name, "project_name": payload.name})
    return project.model_dump()

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Remove a project from tracking."""
    deleted = await registry.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if router:
        await router._emit_event("project:deleted", project_id, {"project_id": project_id})
    return {"deleted": True}

@app.get("/api/discover")
async def discover_directories(path: str = "~"):
    """Browse filesystem directories for project discovery."""
    import os
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        raise HTTPException(status_code=400, detail="Path does not exist")
    dirs = []
    try:
        for entry in sorted(os.listdir(expanded)):
            full = os.path.join(expanded, entry)
            if os.path.isdir(full) and not entry.startswith("."):
                has_git = os.path.isdir(os.path.join(full, ".git"))
                dirs.append({"name": entry, "path": full, "has_git": has_git})
    except PermissionError:
        pass
    return {"directories": dirs, "parent": os.path.dirname(expanded)}
```

**Step 2: Write failing API tests**

```python
# tests/test_api.py — add these tests

@pytest.mark.asyncio
async def test_create_project():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/projects", json={"name": "test-proj", "path": "/tmp"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["project_id"] == "test-proj"

@pytest.mark.asyncio
async def test_create_project_invalid_path():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/projects", json={"name": "bad", "path": "/nonexistent/path"})
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_delete_project():
    async with AsyncClient(app=app, base_url="http://test") as client:
        await client.post("/api/projects", json={"name": "del-me", "path": "/tmp"})
        resp = await client.delete("/api/projects/del-me")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

@pytest.mark.asyncio
async def test_delete_project_not_found():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.delete("/api/projects/nonexistent")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_discover_directories():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/discover?path=/tmp")
    assert resp.status_code == 200
    data = resp.json()
    assert "directories" in data
    assert "parent" in data

@pytest.mark.asyncio
async def test_discover_invalid_path():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/discover?path=/nonexistent")
    assert resp.status_code == 400
```

**Step 3: Run test to verify fail**

Run: `pytest tests/test_api.py -k "create_project or delete_project or discover" -v`
Expected: FAIL — endpoints/methods not found

**Step 4: Run test to verify pass**

Run: `pytest tests/test_api.py -k "create_project or delete_project or discover" -v`
Expected: 6 PASSED

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: 28 passed (22 existing + 6 new)

**Step 6: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat: add project CRUD and discovery API endpoints"
```

---

### Task 4: Add frontend API functions for project CRUD

**Objective:** Add `createProject`, `deleteProject`, `discoverDirs` to dashboard API client

**Files:**
- Modify: `dashboard/lib/api.ts`

**Step 1: Add API functions**

```typescript
// Add to dashboard/lib/api.ts

export interface CreateProjectPayload {
  name: string;
  path: string;
}

export async function createProject(payload: CreateProjectPayload): Promise<ProjectSummary["project"]> {
  const res = await fetch(`${BASE_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function deleteProject(id: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE_URL}/api/projects/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function discoverDirs(path: string = "~"): Promise<{
  directories: { name: string; path: string; has_git: boolean }[];
  parent: string;
}> {
  return fetchApi(`/api/discover?path=${encodeURIComponent(path)}`);
}
```

**Step 2: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat: add project CRUD API functions to dashboard"
```

---

### Task 5: Build AddProjectModal component

**Objective:** Modal with Browse Disk and Manual Entry tabs for adding projects

**Files:**
- Create: `dashboard/components/add-project-modal.tsx`

**Step 1: Write component**

```tsx
"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProject, discoverDirs } from "@/lib/api";
import { Folder, FolderGit2, ChevronRight, Loader2, Plus } from "lucide-react";

interface AddProjectModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function AddProjectModal({ open, onClose, onCreated }: AddProjectModalProps) {
  const [tab, setTab] = useState<"browse" | "manual">("browse");
  const [currentPath, setCurrentPath] = useState("~");
  const [dirs, setDirs] = useState<{ name: string; path: string; has_git: boolean }[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualPath, setManualPath] = useState("");

  useEffect(() => {
    if (open && tab === "browse") {
      loadDirs(currentPath);
    }
  }, [open, tab, currentPath]);

  async function loadDirs(path: string) {
    setLoading(true);
    try {
      const data = await discoverDirs(path);
      setDirs(data.directories);
      setParent(data.parent);
    } catch {
      setError("Failed to browse directory");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(dir: { name: string; path: string }) {
    setLoading(true);
    try {
      await createProject({ name: dir.name, path: dir.path });
      onCreated();
      onClose();
    } catch {
      setError("Failed to create project");
    } finally {
      setLoading(false);
    }
  }

  async function handleManualCreate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await createProject({ name: manualName, path: manualPath });
      onCreated();
      onClose();
    } catch {
      setError("Failed to create project");
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[480px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">Add Project</h2>

        <div className="flex gap-2 mb-4">
          <Button
            variant={tab === "browse" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("browse")}
          >
            Browse Disk
          </Button>
          <Button
            variant={tab === "manual" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("manual")}
          >
            Manual Entry
          </Button>
        </div>

        {tab === "browse" ? (
          <div>
            {parent && (
              <button
                onClick={() => setCurrentPath(parent)}
                className="text-sm text-zinc-400 hover:text-zinc-200 mb-2 flex items-center gap-1"
              >
                <ChevronRight className="w-3 h-3 rotate-180" /> {parent}
              </button>
            )}
            <div className="text-xs text-zinc-500 mb-2 font-mono">{currentPath}</div>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-zinc-500" />
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto space-y-1">
                {dirs.map((d) => (
                  <button
                    key={d.path}
                    onClick={() => handleSelect(d)}
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-zinc-800 text-left text-sm text-zinc-300"
                  >
                    {d.has_git ? (
                      <FolderGit2 className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <Folder className="w-4 h-4 text-zinc-500" />
                    )}
                    <span className="flex-1">{d.name}</span>
                    <Plus className="w-3 h-3 text-zinc-600" />
                  </button>
                ))}
                {dirs.length === 0 && (
                  <p className="text-sm text-zinc-600 py-4 text-center">No subdirectories</p>
                )}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleManualCreate} className="space-y-3">
            <Input
              placeholder="Project name"
              value={manualName}
              onChange={(e) => setManualName(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
            <Input
              placeholder="Absolute path (e.g. /Users/.../my-project)"
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Create Project"}
            </Button>
          </form>
        )}

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <Button variant="ghost" size="sm" onClick={onClose} className="mt-3 w-full">
          Cancel
        </Button>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/add-project-modal.tsx
git commit -m "feat: add AddProjectModal component with browse and manual entry"
```

---

### Task 6: Update sidebar with project list and add button

**Objective:** Show all tracked projects in sidebar with agent counts, add "+ Add Project" link

**Files:**
- Modify: `dashboard/components/sidebar.tsx`

**Step 1: Update sidebar component**

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Home, Plus } from "lucide-react";
import { listProjects } from "@/lib/api";
import { AddProjectModal } from "@/components/add-project-modal";

export function Sidebar() {
  const pathname = usePathname();
  const [projects, setProjects] = useState<any[]>([]);
  const [showAddModal, setShowAddModal] = useState(false);

  useEffect(() => {
    listProjects().then((data) => setProjects(data.projects || []));
  }, []);

  function refreshProjects() {
    listProjects().then((data) => setProjects(data.projects || []));
  }

  return (
    <>
      <aside className="w-64 border-r border-zinc-800 bg-zinc-950 min-h-screen p-4 flex flex-col">
        <div className="mb-6">
          <h1 className="text-lg font-bold text-zinc-100">Agentic OS</h1>
          <p className="text-xs text-zinc-500">Agent Memory Fabric</p>
        </div>
        <nav className="space-y-1 flex-1">
          <Link
            href="/"
            className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
              pathname === "/"
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
            }`}
          >
            <Home className="w-4 h-4" />
            Projects
          </Link>

          {projects.length > 0 && (
            <>
              <div className="text-[10px] font-semibold text-zinc-600 uppercase px-3 pt-4 pb-1">
                Tracked Projects
              </div>
              {projects.map((p) => {
                const active = pathname.startsWith(`/projects/${p.project_id}`);
                return (
                  <Link
                    key={p.project_id}
                    href={`/projects/${p.project_id}`}
                    className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                      active
                        ? "bg-zinc-800 text-zinc-100"
                        : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
                    }`}
                  >
                    <span className="flex-1 truncate">{p.project_name}</span>
                    {p.active_agents > 0 && (
                      <span className="text-[10px] bg-emerald-900 text-emerald-300 px-1.5 py-0.5 rounded-full font-mono">
                        {p.active_agents}
                      </span>
                    )}
                  </Link>
                );
              })}
            </>
          )}

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 w-full mt-2 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Project
          </button>
        </nav>
      </aside>

      <AddProjectModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={refreshProjects}
      />
    </>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/sidebar.tsx
git commit -m "feat: add project list and Add Project to sidebar"
```

---

### Task 7: Add "Add Project" card to projects grid

**Objective:** Add a dashed "+" card to the project grid as visual affordance

**Files:**
- Modify: `dashboard/app/page.tsx`

**Step 1: Update projects page**

```tsx
"use client";

import { useEffect, useState } from "react";
import { listProjects } from "@/lib/api";
import { ProjectCard } from "@/components/project-card";
import { AddProjectModal } from "@/components/add-project-modal";
import { useWebSocket } from "@/lib/use-websocket";
import { Plus } from "lucide-react";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const { lastEvent } = useWebSocket();

  function refresh() {
    listProjects()
      .then((data) => setProjects(data.projects || []))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, []);

  useEffect(() => {
    if (lastEvent && ["graph:updated", "project:created", "project:deleted"].includes(lastEvent.event)) {
      refresh();
    }
  }, [lastEvent]);

  if (loading) {
    return <div className="text-zinc-500">Loading projects...</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Projects</h2>
      </div>
      {projects.length === 0 ? (
        <div className="text-zinc-500">
          <p>No projects tracked yet.</p>
          <button
            onClick={() => setShowAddModal(true)}
            className="text-sm mt-2 text-blue-400 hover:text-blue-300"
          >
            + Add your first project
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <ProjectCard key={p.project_id} project={p} />
          ))}
          {/* Add Project card */}
          <button
            onClick={() => setShowAddModal(true)}
            className="bg-zinc-900 border-2 border-dashed border-zinc-800 hover:border-zinc-700 rounded-xl p-6 flex flex-col items-center justify-center gap-2 text-zinc-600 hover:text-zinc-400 transition-colors min-h-[160px]"
          >
            <Plus className="w-8 h-8" />
            <span className="text-sm">Add Project</span>
          </button>
        </div>
      )}

      <AddProjectModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={refresh}
      />
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/app/page.tsx
git commit -m "feat: add Add Project card and modal to projects page"
```

---

## Phase 2: Graph Explorer

### Task 8: Add graph topology endpoint to daemon

**Objective:** Add `GET /api/projects/:id/graph/topology` that returns full node/edge data for Cytoscape.js

**Files:**
- Modify: `daemon/graph_engine.py`
- Modify: `daemon/api.py`

**Step 1: Add methods to GraphEngine**

```python
# Add to GraphEngine class in daemon/graph_engine.py

async def get_topology(self, project_path: str) -> dict:
    """Return full graph topology (nodes + edges) for visualization."""
    graph_path = Path(project_path) / "graphify-out" / "graph.json"
    if not graph_path.exists():
        return {"nodes": [], "edges": []}
    
    data = await asyncio.to_thread(self._read_graph_json, graph_path)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    
    # Transform to lightweight format for the frontend
    result_nodes = []
    for n in nodes:
        result_nodes.append({
            "id": n.get("id", ""),
            "label": n.get("name", n.get("id", "")),
            "kind": n.get("kind", "Unknown"),
            "community": n.get("community_id", 0),
            "file": n.get("file", ""),
        })
    
    result_edges = []
    for e in edges:
        result_edges.append({
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "kind": e.get("kind", "references"),
        })
    
    return {"nodes": result_nodes, "edges": result_edges}

async def get_communities(self, project_path: str) -> list[dict]:
    """Return community list with sizes."""
    graph_path = Path(project_path) / "graphify-out" / "graph.json"
    if not graph_path.exists():
        return []
    
    data = await asyncio.to_thread(self._read_graph_json, graph_path)
    communities = data.get("communities", {})
    result = []
    for cid, cdata in communities.items():
        result.append({
            "id": cid,
            "name": cdata.get("name", f"Community {cid}"),
            "size": len(cdata.get("members", [])),
        })
    return sorted(result, key=lambda c: c["size"], reverse=True)

async def get_flows(self, project_path: str) -> list[dict]:
    """Return execution flows."""
    graph_path = Path(project_path) / "graphify-out" / "graph.json"
    if not graph_path.exists():
        return []
    
    data = await asyncio.to_thread(self._read_graph_json, graph_path)
    flows = data.get("flows", [])
    result = []
    for f in flows:
        result.append({
            "id": f.get("id", ""),
            "name": f.get("name", ""),
            "criticality": f.get("criticality", 0),
            "node_ids": [s.get("node_id", "") for s in f.get("steps", [])],
        })
    return sorted(result, key=lambda f: f["criticality"], reverse=True)
```

**Step 2: Add API endpoints**

```python
# Add to daemon/api.py

@app.get("/api/projects/{project_id}/graph/topology")
async def get_graph_topology(project_id: str):
    """Get full graph topology for visualization."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    topology = await graph_engine.get_topology(project.project_path)
    return topology

@app.get("/api/projects/{project_id}/graph/communities")
async def get_graph_communities(project_id: str):
    """Get community list for graph filter."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    communities = await graph_engine.get_communities(project.project_path)
    return {"communities": communities}

@app.get("/api/projects/{project_id}/graph/flows")
async def get_graph_flows(project_id: str):
    """Get execution flows for graph highlighting."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    flows = await graph_engine.get_flows(project.project_path)
    return {"flows": flows}
```

**Step 3: Write tests**

```python
# tests/test_graph_engine.py — add

@pytest.mark.asyncio
async def test_get_topology_no_graph():
    engine = GraphEngine()
    result = await engine.get_topology("/nonexistent")
    assert result == {"nodes": [], "edges": []}

@pytest.mark.asyncio
async def test_get_communities_no_graph():
    engine = GraphEngine()
    result = await engine.get_communities("/nonexistent")
    assert result == []

# tests/test_api.py — add

@pytest.mark.asyncio
async def test_get_graph_topology_404():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/projects/nonexistent/graph/topology")
    assert resp.status_code == 404
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: all pass (31+ tests)

**Step 5: Commit**

```bash
git add daemon/graph_engine.py daemon/api.py tests/
git commit -m "feat: add graph topology, communities, and flows endpoints"
```

---

### Task 9: Install Cytoscape.js and add frontend API functions

**Objective:** Add Cytoscape.js dependency and frontend functions for graph data

**Files:**
- Modify: `dashboard/package.json`
- Modify: `dashboard/lib/api.ts`

**Step 1: Install dependencies**

```bash
cd dashboard && npm install cytoscape cytoscape-cose-bilkent
```

**Step 2: Add API functions**

```typescript
// Add to dashboard/lib/api.ts

export interface GraphTopology {
  nodes: { id: string; label: string; kind: string; community: number; file: string }[];
  edges: { source: string; target: string; kind: string }[];
}

export interface CommunityInfo {
  id: string;
  name: string;
  size: number;
}

export interface FlowInfo {
  id: string;
  name: string;
  criticality: number;
  node_ids: string[];
}

export async function getGraphTopology(id: string): Promise<GraphTopology> {
  return fetchApi(`/api/projects/${id}/graph/topology`);
}

export async function getGraphCommunities(id: string): Promise<{ communities: CommunityInfo[] }> {
  return fetchApi(`/api/projects/${id}/graph/communities`);
}

export async function getGraphFlows(id: string): Promise<{ flows: FlowInfo[] }> {
  return fetchApi(`/api/projects/${id}/graph/flows`);
}
```

**Step 3: Commit**

```bash
git add dashboard/package.json dashboard/package-lock.json dashboard/lib/api.ts
git commit -m "feat: add cytoscape.js and graph API functions"
```

---

### Task 10: Build GraphCanvas component

**Objective:** Cytoscape.js wrapper component that renders the force-directed graph

**Files:**
- Create: `dashboard/components/graph-canvas.tsx`

**Step 1: Write component**

```tsx
"use client";

import { useEffect, useRef, useCallback } from "react";
import cytoscape, { Core, EventObject } from "cytoscape";
import coseBilkent from "cytoscape-cose-bilkent";

cytoscape.use(coseBilkent);

const COMMUNITY_COLORS = [
  "#4ade80", "#60a5fa", "#c084fc", "#f59e0b", "#ec4899",
  "#34d399", "#818cf8", "#fbbf24", "#f472b6", "#a78bfa",
];

interface GraphCanvasProps {
  nodes: { id: string; label: string; kind: string; community: number; file: string }[];
  edges: { source: string; target: string; kind: string }[];
  onNodeSelect?: (node: { id: string; label: string; kind: string; community: number; file: string }) => void;
  highlightedNodes?: Set<string>;
  visibleCommunities?: Set<string>;
  showEdges?: boolean;
}

export function GraphCanvas({
  nodes,
  edges,
  onNodeSelect,
  highlightedNodes,
  visibleCommunities,
  showEdges = true,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#27272a",
            label: "data(label)",
            "font-size": "9px",
            color: "#a1a1aa",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 4,
            width: 12,
            height: 12,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": "#3f3f46",
            "curve-style": "bezier",
            opacity: 0.4,
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "background-color": "#f59e0b",
            "border-color": "#fbbf24",
            "border-width": 2,
          },
        },
        {
          selector: "edge.highlighted",
          style: {
            "line-color": "#f59e0b",
            width: 2,
            opacity: 0.8,
          },
        },
      ],
      layout: {
        name: "cose-bilkent",
        animate: false,
        gravity: 0.4,
        idealEdgeLength: 100,
        nodeRepulsion: 8000,
      },
    });

    cy.on("tap", "node", (evt: EventObject) => {
      const node = evt.target;
      onNodeSelect?.({
        id: node.id(),
        label: node.data("label"),
        kind: node.data("kind"),
        community: node.data("community"),
        file: node.data("file"),
      });
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, []);

  // Update elements when data changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Remove old elements
    cy.elements().remove();

    // Add nodes
    nodes.forEach((n) => {
      const colorIdx = (n.community || 0) % COMMUNITY_COLORS.length;
      cy.add({
        group: "nodes",
        data: {
          id: n.id,
          label: n.label,
          kind: n.kind,
          community: n.community,
          file: n.file,
        },
        style: {
          "background-color": COMMUNITY_COLORS[colorIdx],
        },
      });
    });

    // Add edges
    if (showEdges) {
      edges.forEach((e) => {
        cy.add({
          group: "edges",
          data: {
            id: `${e.source}->${e.target}`,
            source: e.source,
            target: e.target,
            kind: e.kind,
          },
        });
      });
    }

    // Run layout
    cy.layout({
      name: "cose-bilkent",
      animate: true,
      animationDuration: 500,
      gravity: 0.4,
      idealEdgeLength: 100,
      nodeRepulsion: 8000,
    }).run();
  }, [nodes, edges, showEdges]);

  // Apply community visibility
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !visibleCommunities) return;

    cy.nodes().forEach((node) => {
      const community = String(node.data("community"));
      if (visibleCommunities.has(community)) {
        node.style("display", "element");
      } else {
        node.style("display", "none");
      }
    });
  }, [visibleCommunities]);

  // Apply highlighting
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !highlightedNodes) return;

    // Reset all
    cy.elements().removeClass("highlighted");

    if (highlightedNodes.size === 0) return;

    // Highlight specific nodes and their edges
    highlightedNodes.forEach((nodeId) => {
      const node = cy.getElementById(nodeId);
      if (node.length > 0) {
        node.addClass("highlighted");
        node.connectedEdges().addClass("highlighted");
      }
    });
  }, [highlightedNodes]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full bg-zinc-950 rounded-lg"
      style={{ minHeight: "500px" }}
    />
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/graph-canvas.tsx
git commit -m "feat: add Cytoscape.js GraphCanvas component"
```

---

### Task 11: Build GraphControls sidebar component

**Objective:** Left sidebar with search, community filter chips, flow selector, view toggles

**Files:**
- Create: `dashboard/components/graph-controls.tsx`

**Step 1: Write component**

```tsx
"use client";

import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

interface CommunityInfo {
  id: string;
  name: string;
  size: number;
}

interface FlowInfo {
  id: string;
  name: string;
  criticality: number;
  node_ids: string[];
}

interface GraphControlsProps {
  communities: CommunityInfo[];
  flows: FlowInfo[];
  visibleCommunities: Set<string>;
  onToggleCommunity: (id: string) => void;
  selectedFlow: string | null;
  onSelectFlow: (id: string | null) => void;
  showEdges: boolean;
  onToggleEdges: () => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
}

const COMMUNITY_COLORS = [
  "bg-emerald-900 text-emerald-300",
  "bg-blue-900 text-blue-300",
  "bg-purple-900 text-purple-300",
  "bg-amber-900 text-amber-300",
  "bg-pink-900 text-pink-300",
];

export function GraphControls({
  communities,
  flows,
  visibleCommunities,
  onToggleCommunity,
  selectedFlow,
  onSelectFlow,
  showEdges,
  onToggleEdges,
  searchQuery,
  onSearchChange,
}: GraphControlsProps) {
  return (
    <div className="w-[220px] bg-zinc-900 border-r border-zinc-800 p-3 overflow-y-auto h-full">
      {/* Search */}
      <div className="relative mb-4">
        <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500" />
        <Input
          placeholder="Search nodes..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-8 bg-zinc-800 border-zinc-700 text-zinc-200 text-xs h-8"
        />
      </div>

      {/* Communities */}
      <div className="mb-4">
        <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">Communities</h4>
        <div className="flex flex-wrap gap-1.5">
          {communities.map((c, i) => {
            const visible = visibleCommunities.has(c.id);
            const colorClass = COMMUNITY_COLORS[i % COMMUNITY_COLORS.length];
            return (
              <button
                key={c.id}
                onClick={() => onToggleCommunity(c.id)}
                className={`text-[10px] px-2 py-1 rounded-full transition-opacity ${
                  visible ? colorClass + " opacity-100" : "bg-zinc-800 text-zinc-600 opacity-60"
                }`}
              >
                {c.name} <span className="opacity-60">{c.size}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Flows */}
      {flows.length > 0 && (
        <div className="mb-4">
          <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">Flows</h4>
          <div className="space-y-0.5">
            <button
              onClick={() => onSelectFlow(null)}
              className={`w-full text-left text-[11px] px-2 py-1 rounded ${
                !selectedFlow ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              Show all
            </button>
            {flows.slice(0, 10).map((f) => (
              <button
                key={f.id}
                onClick={() => onSelectFlow(f.id)}
                className={`w-full text-left text-[11px] px-2 py-1 rounded truncate ${
                  selectedFlow === f.id ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {f.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* View toggles */}
      <div>
        <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">View</h4>
        <label className="flex items-center gap-2 text-[11px] text-zinc-400 cursor-pointer mb-1.5">
          <input
            type="checkbox"
            checked={showEdges}
            onChange={onToggleEdges}
            className="accent-emerald-500 w-3 h-3"
          />
          Show edges
        </label>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/graph-controls.tsx
git commit -m "feat: add GraphControls sidebar component"
```

---

### Task 12: Build NodeDetail floating panel

**Objective:** Floating panel showing selected node details

**Files:**
- Create: `dashboard/components/node-detail.tsx`

**Step 1: Write component**

```tsx
"use client";

import { X } from "lucide-react";

interface NodeDetailProps {
  node: {
    id: string;
    label: string;
    kind: string;
    community: number;
    file: string;
  } | null;
  onClose: () => void;
}

export function NodeDetail({ node, onClose }: NodeDetailProps) {
  if (!node) return null;

  return (
    <div className="absolute bottom-4 right-4 bg-zinc-900 border border-zinc-700 rounded-lg p-3 min-w-[200px] shadow-lg z-10">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-zinc-200 font-mono truncate max-w-[160px]">
          {node.label}
        </h4>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="space-y-1 text-[11px]">
        <div className="flex justify-between">
          <span className="text-zinc-500">Kind</span>
          <span className="text-zinc-300">{node.kind}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Community</span>
          <span className="text-zinc-300">{node.community}</span>
        </div>
        {node.file && (
          <div className="flex justify-between">
            <span className="text-zinc-500">File</span>
            <span className="text-zinc-300 font-mono text-[10px] truncate max-w-[120px]">
              {node.file}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/node-detail.tsx
git commit -m "feat: add NodeDetail floating panel component"
```

---

### Task 13: Rewrite Graph Explorer page with all components

**Objective:** Replace the text-only graph page with the full interactive explorer

**Files:**
- Rewrite: `dashboard/app/projects/[id]/graph/page.tsx`

**Step 1: Rewrite page**

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { getGraphTopology, getGraphCommunities, getGraphFlows, queryGraph } from "@/lib/api";
import { GraphCanvas } from "@/components/graph-canvas";
import { GraphControls } from "@/components/graph-controls";
import { NodeDetail } from "@/components/node-detail";
import { useWebSocket } from "@/lib/use-websocket";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Loader2 } from "lucide-react";

export default function GraphExplorerPage() {
  const { id } = useParams<{ id: string }>();
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [communities, setCommunities] = useState<any[]>([]);
  const [flows, setFlows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [visibleCommunities, setVisibleCommunities] = useState<Set<string>>(new Set());
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [showEdges, setShowEdges] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [nlQuery, setNlQuery] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [topo, comms, flws] = await Promise.all([
        getGraphTopology(id),
        getGraphCommunities(id),
        getGraphFlows(id),
      ]);
      setNodes(topo.nodes || []);
      setEdges(topo.edges || []);
      setCommunities(comms.communities || []);
      setFlows(flws.flows || []);
      // All communities visible by default
      setVisibleCommunities(new Set((comms.communities || []).map((c: any) => String(c.id))));
    } catch {
      // graph not built yet
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  // Subscribe to WebSocket for live updates
  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (event.event === "graph:updated") {
        loadData();
      }
    });
  }, [id, subscribe, loadData]);

  function handleToggleCommunity(communityId: string) {
    setVisibleCommunities((prev) => {
      const next = new Set(prev);
      if (next.has(communityId)) next.delete(communityId);
      else next.add(communityId);
      return next;
    });
  }

  function handleSelectFlow(flowId: string | null) {
    setSelectedFlow(flowId);
    if (!flowId) {
      setHighlightedNodes(new Set());
      return;
    }
    const flow = flows.find((f: any) => f.id === flowId);
    if (flow) {
      setHighlightedNodes(new Set(flow.node_ids));
    }
  }

  function handleSearchChange(q: string) {
    setSearchQuery(q);
    if (!q.trim()) {
      setHighlightedNodes(new Set());
      return;
    }
    const matching = nodes
      .filter((n: any) => n.label.toLowerCase().includes(q.toLowerCase()))
      .map((n: any) => n.id);
    setHighlightedNodes(new Set(matching));
  }

  async function handleNLQuery(e: React.FormEvent) {
    e.preventDefault();
    if (!nlQuery.trim()) return;
    setNlLoading(true);
    try {
      await queryGraph(id, nlQuery);
      // Results could highlight nodes if backend returns node IDs
    } catch {} finally {
      setNlLoading(false);
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-96 text-zinc-500">Loading graph...</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-xl font-bold">Graph Explorer</h2>
          <p className="text-xs text-zinc-500">
            {nodes.length} nodes · {edges.length} edges · {communities.length} communities
          </p>
        </div>
        <form onSubmit={handleNLQuery} className="flex gap-2">
          <Input
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            placeholder="Ask about the codebase..."
            className="bg-zinc-900 border-zinc-700 text-zinc-200 text-sm w-64"
          />
          <Button type="submit" size="sm" disabled={nlLoading}>
            {nlLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          </Button>
        </form>
      </div>

      <div className="flex flex-1 gap-0 border border-zinc-800 rounded-lg overflow-hidden">
        <GraphControls
          communities={communities}
          flows={flows}
          visibleCommunities={visibleCommunities}
          onToggleCommunity={handleToggleCommunity}
          selectedFlow={selectedFlow}
          onSelectFlow={handleSelectFlow}
          showEdges={showEdges}
          onToggleEdges={() => setShowEdges(!showEdges)}
          searchQuery={searchQuery}
          onSearchChange={handleSearchChange}
        />

        <div className="flex-1 relative">
          {nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full text-sm text-zinc-600">
              No graph data yet. Agents need to register and build the graph.
            </div>
          ) : (
            <GraphCanvas
              nodes={nodes}
              edges={edges}
              onNodeSelect={setSelectedNode}
              highlightedNodes={highlightedNodes}
              visibleCommunities={visibleCommunities}
              showEdges={showEdges}
            />
          )}
          <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/app/projects/\[id\]/graph/page.tsx
git commit -m "feat: rewrite graph explorer with Cytoscape.js interactive visualization"
```

---

## Phase 3: Agent Management

### Task 14: Add agent management models and dispatch protocol

**Objective:** Add TaskPayload model and extend AgentInfo with finding count

**Files:**
- Modify: `daemon/models.py`

**Step 1: Add models**

```python
# Add to daemon/models.py

class TaskPayload(BaseModel):
    type: str = "task"
    task_id: str
    target_agent: str
    instruction: str
    priority: str = "medium"
    dispatched_by: str = "dashboard"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class DispatchRequest(BaseModel):
    target_agent: str
    instruction: str
    priority: str = "medium"

class DispatchResult(BaseModel):
    task_id: str
    status: str  # "dispatched"

class AgentDetail(AgentInfo):
    finding_count: int = 0
```

**Step 2: Commit**

```bash
git add daemon/models.py
git commit -m "feat: add task dispatch models"
```

---

### Task 15: Add task dispatch to registry and router

**Objective:** Add tasks table to registry, handle task-*.json files in router

**Files:**
- Modify: `daemon/registry.py`
- Modify: `daemon/router.py`

**Step 1: Add tasks table to registry**

```python
# In AgentRegistry.initialize(), add:
await self.db.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        project TEXT NOT NULL,
        target_agent TEXT NOT NULL,
        instruction TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'pending',
        dispatched_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT
    )
""")

# Add methods:
async def create_task(self, task_id: str, project: str, target_agent: str, instruction: str, priority: str):
    await self.db.execute(
        "INSERT INTO tasks (task_id, project, target_agent, instruction, priority) VALUES (?, ?, ?, ?, ?)",
        (task_id, project, target_agent, instruction, priority),
    )
    await self.db.commit()

async def list_tasks(self, project: str) -> list[dict]:
    cursor = await self.db.execute(
        "SELECT * FROM tasks WHERE project = ? ORDER BY dispatched_at DESC LIMIT 50",
        (project,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]

async def complete_task(self, task_id: str):
    await self.db.execute(
        "UPDATE tasks SET status = 'completed', completed_at = ? WHERE task_id = ?",
        (datetime.now(timezone.utc).isoformat(), task_id),
    )
    await self.db.commit()
```

**Step 2: Add _handle_task to router**

```python
# In Router class, add to handle_file():
elif filename.startswith("task-") and filename.endswith(".json"):
    await self._handle_task(project, path)

# Add handler method:
async def _handle_task(self, project: str, path: Path):
    payload = TaskPayload(**json.loads(path.read_text()))
    await self.registry.create_task(
        payload.task_id, project, payload.target_agent,
        payload.instruction, payload.priority,
    )
    await self._emit_event("agent:dispatched", project, {
        "task_id": payload.task_id,
        "target_agent": payload.target_agent,
        "instruction": payload.instruction,
    })
```

**Step 3: Add dispatch endpoint to API**

```python
# In daemon/api.py
from daemon.models import DispatchRequest, DispatchResult
import uuid

@app.post("/api/projects/{project_id}/dispatch")
async def dispatch_task(project_id: str, payload: DispatchRequest):
    """Dispatch a task to an agent."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    task_id = str(uuid.uuid4())
    task_payload = TaskPayload(
        task_id=task_id,
        target_agent=payload.target_agent,
        instruction=payload.instruction,
        priority=payload.priority,
    )
    
    # Write to inbox (same as agents would pick up)
    import os
    inbox_dir = os.path.expanduser(f"~/.agentic-os/inbox/{project_id}")
    os.makedirs(inbox_dir, exist_ok=True)
    task_path = os.path.join(inbox_dir, f"task-{task_id}.json")
    with open(task_path, "w") as f:
        f.write(task_payload.model_dump_json())
    
    # Also register in SQLite
    await registry.create_task(task_id, project_id, payload.target_agent, payload.instruction, payload.priority)
    
    if router:
        await router._emit_event("agent:dispatched", project_id, {
            "task_id": task_id,
            "target_agent": payload.target_agent,
            "instruction": payload.instruction,
        })
    
    return {"task_id": task_id, "status": "dispatched"}

@app.get("/api/projects/{project_id}/dispatches")
async def list_dispatches(project_id: str):
    """List task dispatches for a project."""
    tasks = await registry.list_tasks(project_id)
    return {"dispatches": tasks}
```

**Step 4: Extend agent list endpoint with finding counts**

In the existing `list_agents` endpoint, extend the agent info with finding count by querying the tasks table.

**Step 5: Write tests**

```python
# tests/test_api.py — add

@pytest.mark.asyncio
async def test_dispatch_task():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # First create project
        await client.post("/api/projects", json={"name": "dp", "path": "/tmp"})
        resp = await client.post("/api/projects/dp/dispatch", json={
            "target_agent": "claude-code", "instruction": "Review auth", "priority": "high"
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "dispatched"
    assert "task_id" in data

@pytest.mark.asyncio
async def test_list_dispatches():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/projects/dp/dispatches")
    assert resp.status_code == 200
    assert "dispatches" in resp.json()
```

**Step 6: Run tests**

Run: `pytest tests/ -v`
Expected: all pass

**Step 7: Commit**

```bash
git add daemon/models.py daemon/registry.py daemon/router.py daemon/api.py tests/
git commit -m "feat: add task dispatch protocol and API endpoints"
```

---

### Task 16: Add frontend API functions for agents

**Objective:** Add dispatch, list dispatches functions to dashboard API client

**Files:**
- Modify: `dashboard/lib/api.ts`

**Step 1: Add functions**

```typescript
// Add to dashboard/lib/api.ts

export async function dispatchTask(
  projectId: string,
  payload: { target_agent: string; instruction: string; priority?: string }
): Promise<{ task_id: string; status: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/dispatch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function listDispatches(projectId: string): Promise<{
  dispatches: { task_id: string; target_agent: string; instruction: string; status: string; dispatched_at: string }[];
}> {
  return fetchApi(`/api/projects/${projectId}/dispatches`);
}
```

**Step 2: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat: add dispatch API functions to dashboard"
```

---

### Task 17: Build AgentCard component

**Objective:** Rich agent card with status, capabilities, finding count

**Files:**
- Create: `dashboard/components/agent-card.tsx`

**Step 1: Write component**

```tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface AgentCardProps {
  agent: {
    agent_id: string;
    agent_name: string;
    version: string;
    status: "online" | "offline" | "working";
    capabilities: string[];
    last_heartbeat: string | null;
    registered_at: string;
    finding_count?: number;
  };
}

export function AgentCard({ agent }: AgentCardProps) {
  const [expanded, setExpanded] = useState(false);

  const initials = agent.agent_name
    .split("-")
    .map((w) => w[0]?.toUpperCase())
    .join("")
    .slice(0, 2);

  const statusColor = {
    online: "bg-emerald-900/50 border-emerald-700 text-emerald-300",
    working: "bg-amber-900/50 border-amber-700 text-amber-300",
    offline: "bg-zinc-800/50 border-zinc-700 text-zinc-500",
  };

  const dotColor = {
    online: "bg-emerald-400",
    working: "bg-amber-400",
    offline: "bg-zinc-600",
  };

  const avatarBg = {
    online: "bg-emerald-900 text-emerald-300",
    working: "bg-amber-900 text-amber-300",
    offline: "bg-zinc-800 text-zinc-500",
  };

  const timeAgo = agent.last_heartbeat
    ? (() => {
        const diff = Date.now() - new Date(agent.last_heartbeat).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return "just now";
        if (mins < 60) return `${mins}m ago`;
        return `${Math.floor(mins / 60)}h ago`;
      })()
    : "never";

  return (
    <div
      className={`border rounded-xl p-4 cursor-pointer transition-colors ${statusColor[agent.status]}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-3">
        <div
          className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold text-sm ${avatarBg[agent.status]}`}
        >
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="font-semibold text-sm text-zinc-100">{agent.agent_name}</h4>
            <div className={`w-2 h-2 rounded-full ${dotColor[agent.status]}`} />
          </div>
          <p className="text-[11px] text-zinc-500">
            {agent.version} · Registered {timeAgo}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-zinc-400">
          <span>{agent.capabilities.length} capabilities</span>
          {agent.finding_count !== undefined && <span>{agent.finding_count} findings</span>}
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </div>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-zinc-700/50">
          <div className="flex flex-wrap gap-1.5 mb-2">
            {agent.capabilities.map((c) => (
              <span
                key={c}
                className="text-[10px] bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded-full"
              >
                {c}
              </span>
            ))}
          </div>
          <div className="text-[10px] text-zinc-600">
            Last heartbeat: {agent.last_heartbeat ? new Date(agent.last_heartbeat).toLocaleString() : "never"}
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/agent-card.tsx
git commit -m "feat: add expandable AgentCard component"
```

---

### Task 18: Build AgentWiring component

**Objective:** Horizontal chain diagram showing agent-relationship with findings and dispatched tasks

**Files:**
- Create: `dashboard/components/agent-wiring.tsx`

**Step 1: Write component**

```tsx
"use client";

interface AgentInfo {
  agent_id: string;
  agent_name: string;
  status: string;
  finding_count?: number;
}

interface DispatchInfo {
  task_id: string;
  target_agent: string;
  instruction: string;
  status: string;
}

interface AgentWiringProps {
  agents: AgentInfo[];
  dispatches: DispatchInfo[];
}

export function AgentWiring({ agents, dispatches }: AgentWiringProps) {
  if (agents.length === 0) {
    return (
      <div className="text-sm text-zinc-600 text-center py-8">
        No agents registered yet
      </div>
    );
  }

  const initials = (name: string) =>
    name
      .split("-")
      .map((w) => w[0]?.toUpperCase())
      .join("")
      .slice(0, 2);

  const colors = [
    { bg: "bg-emerald-900", border: "border-emerald-700", text: "text-emerald-300", dot: "bg-emerald-400" },
    { bg: "bg-blue-900", border: "border-blue-700", text: "text-blue-300", dot: "bg-blue-400" },
    { bg: "bg-purple-900", border: "border-purple-700", text: "text-purple-300", dot: "bg-purple-400" },
  ];

  return (
    <div className="flex items-center gap-0 justify-center flex-wrap py-4">
      {agents.map((agent, i) => {
        const color = colors[i % colors.length];
        return (
          <div key={agent.agent_id} className="flex items-center gap-0">
            {/* Agent node */}
            <div className="flex flex-col items-center mx-3">
              <div
                className={`w-14 h-14 rounded-full ${color.bg} border-2 ${color.border} flex items-center justify-center ${color.text} font-bold text-lg`}
              >
                {initials(agent.agent_name)}
              </div>
              <span className="text-[10px] text-zinc-400 mt-1.5">{agent.agent_name}</span>
              <span className="text-[9px] text-zinc-600">{agent.finding_count || 0} findings</span>
              <div className={`w-1.5 h-1.5 rounded-full ${color.dot} mt-0.5`} />
            </div>

            {/* Arrow to next agent or task */}
            {i < agents.length - 1 && (
              <div className="flex items-center text-zinc-700 text-lg mx-1">
                ━━━▶
              </div>
            )}
          </div>
        );
      })}

      {/* Pending tasks as dashed nodes */}
      {dispatches
        .filter((d) => d.status === "pending")
        .slice(0, 3)
        .map((d) => (
          <div key={d.task_id} className="flex items-center gap-0">
            <div className="flex items-center text-zinc-700 text-lg mx-1">━━━▶</div>
            <div className="flex flex-col items-center mx-3">
              <div className="w-12 h-12 rounded-xl bg-zinc-900 border-2 border-dashed border-zinc-600 flex items-center justify-center text-zinc-500 text-xs">
                📋
              </div>
              <span className="text-[10px] text-zinc-500 mt-1.5">Task</span>
              <span className="text-[9px] text-zinc-600 truncate max-w-[80px]">{d.target_agent}</span>
              <span className="text-[8px] text-amber-500 mt-0.5">pending</span>
            </div>
          </div>
        ))}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/agent-wiring.tsx
git commit -m "feat: add AgentWiring chain diagram component"
```

---

### Task 19: Build DispatchModal component

**Objective:** Modal form for dispatching tasks to agents

**Files:**
- Create: `dashboard/components/dispatch-modal.tsx`

**Step 1: Write component**

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { dispatchTask } from "@/lib/api";
import { Loader2, Send } from "lucide-react";

interface DispatchModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  agents: { agent_name: string; agent_id: string }[];
  onDispatched: () => void;
}

export function DispatchModal({ open, onClose, projectId, agents, onDispatched }: DispatchModalProps) {
  const [target, setTarget] = useState("");
  const [instruction, setInstruction] = useState("");
  const [priority, setPriority] = useState("medium");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!target || !instruction.trim()) return;
    setLoading(true);
    setError("");
    try {
      await dispatchTask(projectId, { target_agent: target, instruction, priority });
      onDispatched();
      onClose();
      setInstruction("");
    } catch {
      setError("Failed to dispatch task");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[480px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">Dispatch Task</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">Target Agent</label>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
              required
            >
              <option value="">Select agent...</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_name}>
                  {a.agent_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-zinc-400 mb-1 block">Instruction</label>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="e.g. Review the auth module for security issues"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-24 resize-none"
              required
            />
          </div>

          <div>
            <label className="text-xs text-zinc-400 mb-1 block">Priority</label>
            <div className="flex gap-2">
              {["low", "medium", "high"].map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                    priority === p
                      ? p === "high"
                        ? "border-red-700 bg-red-900/30 text-red-300"
                        : p === "medium"
                        ? "border-amber-700 bg-amber-900/30 text-amber-300"
                        : "border-zinc-600 bg-zinc-800 text-zinc-400"
                      : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={loading} className="flex-1">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              <span className="ml-2">Dispatch</span>
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/dispatch-modal.tsx
git commit -m "feat: add DispatchModal component"
```

---

### Task 20: Build DispatchHistory component

**Objective:** Table showing past task dispatches with status

**Files:**
- Create: `dashboard/components/dispatch-history.tsx`

**Step 1: Write component**

```tsx
"use client";

interface DispatchInfo {
  task_id: string;
  target_agent: string;
  instruction: string;
  status: string;
  dispatched_at: string;
  priority?: string;
}

interface DispatchHistoryProps {
  dispatches: DispatchInfo[];
}

export function DispatchHistory({ dispatches }: DispatchHistoryProps) {
  const statusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-emerald-900/50 text-emerald-300 border-emerald-700";
      case "pending":
        return "bg-amber-900/50 text-amber-300 border-amber-700";
      case "failed":
        return "bg-red-900/50 text-red-300 border-red-700";
      default:
        return "bg-zinc-800 text-zinc-400 border-zinc-700";
    }
  };

  if (dispatches.length === 0) {
    return (
      <div className="text-sm text-zinc-600 text-center py-6">
        No tasks dispatched yet
      </div>
    );
  }

  return (
    <div className="border border-zinc-800 rounded-lg overflow-hidden">
      <div className="grid grid-cols-[1fr_100px_80px_140px] gap-2 px-4 py-2 bg-zinc-900 text-[11px] text-zinc-500 font-semibold uppercase border-b border-zinc-800">
        <span>Instruction</span>
        <span>Target</span>
        <span>Status</span>
        <span className="text-right">Dispatched</span>
      </div>
      {dispatches.map((d) => (
        <div
          key={d.task_id}
          className="grid grid-cols-[1fr_100px_80px_140px] gap-2 px-4 py-2.5 border-b border-zinc-800/50 text-sm hover:bg-zinc-900/50"
        >
          <span className="text-zinc-300 truncate">{d.instruction}</span>
          <span className="text-zinc-400 text-xs font-mono">{d.target_agent}</span>
          <span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${statusBadge(d.status)}`}>
              {d.status}
            </span>
          </span>
          <span className="text-zinc-600 text-xs text-right">
            {new Date(d.dispatched_at).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/dispatch-history.tsx
git commit -m "feat: add DispatchHistory table component"
```

---

### Task 21: Build Agent Management page

**Objective:** New `/projects/[id]/agents` page with agent cards, wiring, dispatch modal, and history

**Files:**
- Create: `dashboard/app/projects/[id]/agents/page.tsx`

**Step 1: Write page**

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { getProject, dispatchTask, listDispatches } from "@/lib/api";
import { AgentCard } from "@/components/agent-card";
import { AgentWiring } from "@/components/agent-wiring";
import { DispatchModal } from "@/components/dispatch-modal";
import { DispatchHistory } from "@/components/dispatch-history";
import { Button } from "@/components/ui/button";
import { useWebSocket } from "@/lib/use-websocket";
import { Send } from "lucide-react";

export default function AgentManagementPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [dispatches, setDispatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showDispatch, setShowDispatch] = useState(false);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    try {
      const [projectData, dispatchData] = await Promise.all([
        getProject(id),
        listDispatches(id),
      ]);
      setData(projectData);
      setDispatches(dispatchData.dispatches || []);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (["agent:online", "agent:offline", "agent:dispatched", "task:completed"].includes(event.event)) {
        loadData();
      }
    });
  }, [id, subscribe, loadData]);

  if (loading) return <div className="text-zinc-500">Loading...</div>;
  if (!data) return <div className="text-zinc-500">Project not found</div>;

  const { agents } = data;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">Agents</h2>
          <p className="text-sm text-zinc-500">{agents.length} agent{agents.length !== 1 ? "s" : ""} registered</p>
        </div>
        {agents.length > 0 && (
          <Button onClick={() => setShowDispatch(true)} size="sm">
            <Send className="w-3.5 h-3.5 mr-2" /> Dispatch Task
          </Button>
        )}
      </div>

      {/* Agent Cards */}
      <div className="space-y-3 mb-8">
        {agents.length === 0 ? (
          <p className="text-sm text-zinc-600">No agents registered yet. Agents appear when they write register.json to ~/.agentic-os/inbox/</p>
        ) : (
          agents.map((a: any) => <AgentCard key={a.agent_id} agent={a} />)
        )}
      </div>

      {/* Agent Wiring */}
      <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Agent Wiring</h3>
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-8">
        <AgentWiring agents={agents} dispatches={dispatches} />
      </div>

      {/* Dispatch History */}
      <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Dispatch History</h3>
      <DispatchHistory dispatches={dispatches} />

      {/* Dispatch Modal */}
      <DispatchModal
        open={showDispatch}
        onClose={() => setShowDispatch(false)}
        projectId={id}
        agents={agents}
        onDispatched={loadData}
      />
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/app/projects/\[id\]/agents/page.tsx
git commit -m "feat: add Agent Management page with wiring and dispatch"
```

---

## Phase 4: Integration & Polish

### Task 22: Add agent navigation to sidebar and project detail

**Objective:** Link to agent management from sidebar (per-project) and project detail page

**Files:**
- Modify: `dashboard/components/sidebar.tsx`
- Modify: `dashboard/app/projects/[id]/page.tsx`

**Step 1: Update sidebar project links**

In the sidebar, when a project is the active route, show sub-navigation links: "Overview", "Graph", "Agents". Replace the single link with expandable sub-items.

**Step 2: Update project detail page**

Add a link/button to navigate to Agents page from the agents section on project detail.

**Step 3: Commit**

```bash
git add dashboard/components/sidebar.tsx dashboard/app/projects/\[id\]/page.tsx
git commit -m "feat: add agent navigation to sidebar and project detail"
```

---

### Task 23: Run full test suite and verify

**Objective:** Run all tests, verify daemon starts, verify dashboard compiles

**Files:**
- None (verification only)

**Step 1: Run Python tests**

```bash
cd /Users/mohamedabdulrahman/Mohamed-Hussien/my-projects/agentic-os
python -m pytest tests/ -v
```
Expected: all tests pass

**Step 2: Verify daemon starts**

```bash
cd /Users/mohamedabdulrahman/Mohamed-Hussien/my-projects/agentic-os
python -c "from daemon.api import app; print('FastAPI app OK')"
```
Expected: `FastAPI app OK`

**Step 3: Check dashboard TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

**Step 4: Commit any final fixes**

```bash
git add -A && git commit -m "chore: final integration and test verification"
```

---

## Summary

| Phase | Tasks | New Files | Modified Files |
|-------|-------|-----------|----------------|
| Phase 1: Project CRUD | 7 tasks | 1 (AddProjectModal) | 5 (models, registry, api, api.ts, sidebar, page) |
| Phase 2: Graph Explorer | 6 tasks | 3 (GraphCanvas, GraphControls, NodeDetail) | 3 (graph_engine, api, graph page) |
| Phase 3: Agent Management | 8 tasks | 5 (AgentCard, AgentWiring, DispatchModal, DispatchHistory, agents page) | 4 (models, registry, router, api) |
| Phase 4: Integration | 2 tasks | 0 | 2 (sidebar, project detail) |

**Total: 23 tasks, 9 new files, 14 modified files**
