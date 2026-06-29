# Loom OS Phase 2 — Agent Discovery / Directory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Source spec:** [docs/superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md](../superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md) — Feature #6
> **Parent plan:** [docs/plans/2026-06-29-post-parity-roadmap-implementation.md](2026-06-29-post-parity-roadmap-implementation.md) — Phase 2

**Goal:** Enrich agent capability data into a structured schema, expose a capability-listing + matching API, and ship an "Agent Directory" dashboard view — all backward-compatible with the existing comma-string capabilities.

**Architecture:** Additive over the existing `AgentRegistry`. A new `AgentCapability` Pydantic model (`{name, description, tools, models, status}`) is stored as JSON in a new `structured_capabilities` TEXT column on the `agents` table. The old `capabilities` column (flat string list) stays for backward compat. A keyword-match endpoint filters agents by capability need. Dashboard gets a new directory page.

**Tech Stack:** Python 3.11+ (Pydantic, aiosqlite), TypeScript (Next.js 16, React 19, shadcn).

## Global Constraints (inherited)

- Single-process daemon — no new infrastructure.
- Filesystem inbox protocol preserved — extend, never replace.
- Existing test suite must stay green; every new daemon module gets `tests/test_<module>.py`.
- WebSocket events emitted for new state changes.
- Every user-facing feature ships a dashboard surface.

---

## Task 6.1: `AgentCapability` model + extend `AgentInfo`

**Files:**
- Modify: `daemon/models.py`
- Test: `tests/test_api.py` (existing — verify model serialization)

**Interfaces:**
- Produces: `AgentCapability(BaseModel)` with `name: str`, `description: str = ""`, `tools: list[str] = []`, `models: list[str] = []`, `status: str = "active"`.
- Produces: `AgentInfo` gains `structured_capabilities: list[AgentCapability] = []`.
- Consumes: existing `AgentInfo` (backward compat — `capabilities: list[str]` stays).

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_agent_info_serializes_structured_capabilities(client):
    """AgentInfo with structured capabilities serializes correctly."""
    from daemon.models import AgentInfo, AgentCapability
    agent = AgentInfo(
        agent_id="test-proj",
        agent_name="test",
        version="1.0",
        project="proj",
        capabilities=["code-analysis"],
        structured_capabilities=[
            AgentCapability(name="code-analysis", description="Reviews code", tools=["gh"], models=["gpt-4o"]),
        ],
    )
    d = agent.model_dump()
    assert d["structured_capabilities"][0]["name"] == "code-analysis"
    assert d["structured_capabilities"][0]["tools"] == ["gh"]
    # Old field still present
    assert d["capabilities"] == ["code-analysis"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_agent_info_serializes_structured_capabilities -v`
Expected: FAIL — `ImportError: cannot import name 'AgentCapability'`

- [ ] **Step 3: Write minimal implementation**

```python
# Add to daemon/models.py, after AgentStatus enum, before AgentInfo:

class AgentCapability(BaseModel):
    """Structured capability descriptor for agent discovery/matching."""
    name: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    status: str = "active"  # active | idle | disabled


# Modify AgentInfo to add the new field:
class AgentInfo(BaseModel):
    agent_id: str
    agent_name: str
    version: str
    project: str
    capabilities: list[str]
    structured_capabilities: list[AgentCapability] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.ONLINE
    last_heartbeat: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (new test + existing tests stay green)

- [ ] **Step 5: Commit**

```bash
git add daemon/models.py tests/test_api.py
git commit -m "feat(models): add AgentCapability schema + structured_capabilities on AgentInfo"
```

---

## Task 6.2: Registry migration — `structured_capabilities` column

**Files:**
- Modify: `daemon/registry.py` (schema migration + `_row_to_agent` + `upsert_agent`)
- Test: `tests/test_registry.py` (existing — verify backward compat)

**Interfaces:**
- Produces: `agents` table gains `structured_capabilities TEXT DEFAULT '[]'` column.
- `upsert_agent` stores `json.dumps([c.model_dump() for c in agent.structured_capabilities])`.
- `_row_to_agent` parses the JSON back into `list[AgentCapability]`.
- Backward compat: agents registered without structured_capabilities get `[]`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_registry.py
import pytest
from daemon.models import AgentInfo, AgentCapability
from daemon.registry import AgentRegistry


@pytest.mark.asyncio
async def test_upsert_and_retrieve_structured_capabilities(tmp_path):
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    agent = AgentInfo(
        agent_id="claude-code-proj",
        agent_name="claude-code",
        version="1.0",
        project="proj",
        capabilities=["code-analysis"],
        structured_capabilities=[
            AgentCapability(name="review", description="PR review", tools=["gh"], models=["claude-sonnet-4"]),
            AgentCapability(name="test", description="Writes tests", tools=["pytest"]),
        ],
    )
    await registry.upsert_agent(agent)
    retrieved = await registry.get_agent("claude-code-proj")

    assert len(retrieved.structured_capabilities) == 2
    assert retrieved.structured_capabilities[0].name == "review"
    assert retrieved.structured_capabilities[0].tools == ["gh"]
    assert retrieved.structured_capabilities[1].name == "test"


@pytest.mark.asyncio
async def test_agent_without_structured_capabilities_still_works(tmp_path):
    """Backward compat: agents registered the old way get empty structured_capabilities."""
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    agent = AgentInfo(
        agent_id="codex-proj",
        agent_name="codex",
        version="1.0",
        project="proj",
        capabilities=["code-analysis"],
    )
    await registry.upsert_agent(agent)
    retrieved = await registry.get_agent("codex-proj")

    assert retrieved.structured_capabilities == []
    assert retrieved.capabilities == ["code-analysis"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py::test_upsert_and_retrieve_structured_capabilities -v`
Expected: FAIL — `structured_capabilities` column doesn't exist (or `_row_to_agent` doesn't parse it)

- [ ] **Step 3: Implement the migration + storage**

```python
# daemon/registry.py — in initialize(), after the agents table CREATE, add:
        # Migration: add structured_capabilities column if it doesn't exist.
        # ALTER TABLE ... ADD COLUMN is idempotent-safe with this check.
        cursor = await self.db.execute("PRAGMA table_info(agents)")
        cols = [r[1] for r in await cursor.fetchall()]
        if "structured_capabilities" not in cols:
            await self.db.execute(
                "ALTER TABLE agents ADD COLUMN structured_capabilities TEXT DEFAULT '[]'"
            )
        await self.db.commit()

# daemon/registry.py — in upsert_agent, add structured_capabilities to the INSERT:
    async def upsert_agent(self, agent: AgentInfo):
        await self.db.execute(
            """INSERT OR REPLACE INTO agents
               (agent_id, agent_name, version, project, capabilities,
                structured_capabilities, status, last_heartbeat, registered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent.agent_id,
                agent.agent_name,
                agent.version,
                agent.project,
                json.dumps(agent.capabilities),
                json.dumps([c.model_dump() for c in agent.structured_capabilities]),
                agent.status.value,
                agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                agent.registered_at.isoformat(),
            ),
        )
        await self.db.commit()

# daemon/registry.py — in _row_to_agent, parse structured_capabilities:
    @staticmethod
    def _row_to_agent(row) -> AgentInfo:
        from daemon.models import AgentCapability
        raw_caps = row["structured_capabilities"] if "structured_capabilities" in row.keys() else "[]"
        try:
            sc = [AgentCapability(**c) for c in json.loads(raw_caps or "[]")]
        except (json.JSONDecodeError, TypeError):
            sc = []
        return AgentInfo(
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            version=row["version"],
            project=row["project"],
            capabilities=json.loads(row["capabilities"]),
            structured_capabilities=sc,
            status=AgentStatus(row["status"]),
            last_heartbeat=(
                datetime.fromisoformat(row["last_heartbeat"])
                if row["last_heartbeat"]
                else None
            ),
            registered_at=datetime.fromisoformat(row["registered_at"]),
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_registry.py tests/test_api.py -v`
Expected: PASS (new tests + existing tests stay green — backward compat confirmed)

- [ ] **Step 5: Commit**

```bash
git add daemon/registry.py tests/test_registry.py
git commit -m "feat(registry): store structured_capabilities with backward-compatible migration"
```

---

## Task 6.3: `registry.match_capability(project, need)` method

**Files:**
- Modify: `daemon/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `async match_capability(self, project: str, need: str) -> list[AgentInfo]` — keyword-matches `need` against both `capabilities` (flat strings) and `structured_capabilities[].name` / `.description`. Returns matching agents, sorted by status (online first).

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_registry.py
@pytest.mark.asyncio
async def test_match_capability_returns_only_matching_agents(tmp_path):
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    # Agent 1: has "review" capability
    await registry.upsert_agent(AgentInfo(
        agent_id="reviewer-proj", agent_name="reviewer", version="1.0",
        project="proj", capabilities=["review"],
        structured_capabilities=[AgentCapability(name="review", description="PR review")],
    ))
    # Agent 2: has "test" capability
    await registry.upsert_agent(AgentInfo(
        agent_id="tester-proj", agent_name="tester", version="1.0",
        project="proj", capabilities=["testing"],
        structured_capabilities=[AgentCapability(name="test", description="Writes tests")],
    ))

    matches = await registry.match_capability("proj", "review")
    assert len(matches) == 1
    assert matches[0].agent_name == "reviewer"


@pytest.mark.asyncio
async def test_match_capability_matches_flat_string_capabilities(tmp_path):
    """Old-style flat capabilities still match (backward compat)."""
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    await registry.upsert_agent(AgentInfo(
        agent_id="codex-proj", agent_name="codex", version="1.0",
        project="proj", capabilities=["code-analysis", "bug-finding"],
    ))

    matches = await registry.match_capability("proj", "code-analysis")
    assert len(matches) == 1
    assert matches[0].agent_name == "codex"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py::test_match_capability_returns_only_matching_agents -v`
Expected: FAIL — `AttributeError: 'AgentRegistry' object has no attribute 'match_capability'`

- [ ] **Step 3: Implement `match_capability`**

```python
# Add to daemon/registry.py, after list_agents:

    async def match_capability(self, project: str, need: str) -> list[AgentInfo]:
        """Find agents whose capabilities match the given need (keyword match).

        Searches both flat ``capabilities`` strings and structured
        ``AgentCapability.name`` / ``.description`` fields. Returns matching
        agents sorted by status (online first, then working, then offline).
        """
        agents = await self.list_agents(project)
        need_lower = need.lower()
        matches: list[AgentInfo] = []
        for a in agents:
            # Check flat capabilities
            if any(need_lower in c.lower() for c in a.capabilities):
                matches.append(a)
                continue
            # Check structured capabilities
            for sc in a.structured_capabilities:
                if need_lower in sc.name.lower() or need_lower in sc.description.lower():
                    matches.append(a)
                    break
        # Sort: online > working > offline
        status_order = {"online": 0, "working": 1, "offline": 2}
        matches.sort(key=lambda a: status_order.get(a.status.value, 3))
        return matches
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/registry.py tests/test_registry.py
git commit -m "feat(registry): add match_capability for agent discovery"
```

---

## Task 6.4: API capability-listing + match endpoints

**Files:**
- Modify: `daemon/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `GET /api/projects/{project_id}/agents/match?need=review` → `{"matches": [AgentInfo.model_dump()]}`.
- The existing `GET /api/projects/{project_id}/agents` already returns `structured_capabilities` (since `AgentInfo` now has the field and `_row_to_agent` populates it) — verify this in a test.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_agents_match_endpoint(client):
    """GET /agents/match?need=code-analysis returns matching agents."""
    resp = client.get("/api/projects/noor/agents/match?need=code-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert "matches" in body
    # The fixture seeded an agent with capabilities=["code-analysis"]
    assert len(body["matches"]) >= 1
    assert body["matches"][0]["agent_name"] == "claude-code"


def test_agents_match_endpoint_no_results(client):
    """GET /agents/match?need=nonexistent returns empty list."""
    resp = client.get("/api/projects/noor/agents/match?need=nonexistent-capability")
    assert resp.status_code == 200
    assert resp.json()["matches"] == []


def test_agents_list_includes_structured_capabilities(client):
    """GET /agents response includes structured_capabilities field."""
    resp = client.get("/api/projects/noor/agents")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) > 0
    assert "structured_capabilities" in agents[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_agents_match_endpoint -v`
Expected: FAIL — 404 (route not defined)

- [ ] **Step 3: Implement the match endpoint**

```python
# Add to daemon/api.py, after the existing list_agents endpoint:

@app.get("/api/projects/{project_id}/agents/match")
async def match_agents(project_id: str, need: str = ""):
    """Find agents whose capabilities match the given need (keyword match)."""
    if not need:
        raise HTTPException(status_code=400, detail="Missing query parameter 'need'")
    matches = await registry.match_capability(project_id, need)
    return {"matches": [a.model_dump() for a in matches]}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -v`
Expected: PASS (new tests + existing tests)

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat(api): add agent capability match endpoint"
```

---

## Task 6.5: Dashboard — Agent Directory component + page

**Files:**
- Create: `dashboard/components/agent-directory.tsx`
- Create: `dashboard/app/[locale]/projects/[id]/directory/page.tsx`
- Modify: `dashboard/components/sidebar.tsx` (add Directory nav link)
- Modify: `dashboard/lib/api.ts` (add `matchAgents` fetch helper)

**Interfaces:**
- Consumes: `GET /api/projects/{id}/agents` (structured_capabilities), `GET /api/projects/{id}/agents/match?need=...`.

- [ ] **Step 1: Add `matchAgents` to `lib/api.ts`**

```typescript
// Add to dashboard/lib/api.ts, after unregisterAgent:

export async function matchAgents(
  projectId: string,
  need: string,
): Promise<{ matches: AgentInfo[] }> {
  return fetchApi(`/api/projects/${projectId}/agents/match?need=${encodeURIComponent(need)}`);
}
```

- [ ] **Step 2: Create `agent-directory.tsx`**

```tsx
// dashboard/components/agent-directory.tsx
"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { AgentInfo, matchAgents } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Search } from "lucide-react";

interface AgentDirectoryProps {
  projectId: string;
  agents: AgentInfo[];
}

export function AgentDirectory({ projectId, agents }: AgentDirectoryProps) {
  const t = useTranslations("AgentDirectory");
  const [need, setNeed] = useState("");
  const [matches, setMatches] = useState<AgentInfo[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSearch(q: string) {
    setNeed(q);
    if (q.length < 2) {
      setMatches(null);
      return;
    }
    setLoading(true);
    try {
      const data = await matchAgents(projectId, q);
      setMatches(data.matches);
    } catch {
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }

  const displayAgents = matches ?? agents;

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 rtl:right-3 rtl:left-auto" />
        <Input
          placeholder={t("searchPlaceholder")}
          value={need}
          onChange={(e) => handleSearch(e.target.value)}
          className="ps-9 bg-zinc-900 border-zinc-700 text-zinc-200 rtl:pe-9"
        />
      </div>

      {loading && <p className="text-zinc-500 text-xs">{t("searching")}</p>}

      {displayAgents.length === 0 && !loading ? (
        <p className="text-zinc-600 text-sm">{t("noAgents")}</p>
      ) : (
        <div className="space-y-2">
          {displayAgents.map((agent) => (
            <Card key={agent.agent_id} className="bg-zinc-900 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-sm text-zinc-100">{agent.agent_name}</span>
                  <span className={`text-[10px] uppercase ${
                    agent.status === "online" ? "text-emerald-400" :
                    agent.status === "working" ? "text-amber-400" : "text-zinc-500"
                  }`}>{agent.status}</span>
                </div>
                {agent.structured_capabilities.length > 0 ? (
                  <div className="space-y-1 mt-2">
                    {agent.structured_capabilities.map((sc) => (
                      <div key={sc.name} className="text-xs">
                        <span className="text-indigo-400 font-medium">{sc.name}</span>
                        {sc.description && <span className="text-zinc-500"> — {sc.description}</span>}
                        {sc.tools.length > 0 && (
                          <span className="text-zinc-600 ms-2">tools: {sc.tools.join(", ")}</span>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {agent.capabilities.map((c) => (
                      <span key={c} className="text-[10px] bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded-full">
                        {c}
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create the directory page**

```tsx
// dashboard/app/[locale]/projects/[id]/directory/page.tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { getProject } from "@/lib/api";
import type { ProjectSummary } from "@/lib/api";
import { AgentDirectory } from "@/components/agent-directory";
import { useWebSocket } from "@/lib/use-websocket";

export default function AgentDirectoryPage() {
  const t = useTranslations("AgentDirectory");
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    try {
      const projectData = await getProject(id);
      setData(projectData);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (["agent:online", "agent:offline"].includes(event.event)) {
        loadData();
      }
    });
  }, [id, subscribe, loadData]);

  if (loading) return <div className="text-zinc-500">{t("loading")}</div>;
  if (!data) return <div className="text-zinc-500">{t("notFound")}</div>;

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold">{t("heading")}</h2>
        <p className="text-sm text-zinc-500">{t("subtitle", { count: data.agents.length })}</p>
      </div>
      <AgentDirectory projectId={id} agents={data.agents} />
    </div>
  );
}
```

- [ ] **Step 4: Add Directory link to sidebar**

In `dashboard/components/sidebar.tsx`, inside the project sub-navigation (where Overview / Graph / Agents links are), add:

```tsx
<Link
  href={`/projects/${p.project_id}/directory`}
  className={`flex items-center gap-2 px-3 py-1.5 rounded text-[11px] transition-colors ${
    pathname.includes("/directory")
      ? "text-zinc-200 bg-zinc-800/50"
      : "text-zinc-500 hover:text-zinc-300"
  }`}
>
  <Users className="w-3 h-3" /> {t("directory")}
</Link>
```

Import `Users` from `lucide-react` (already imported). Add `"directory": "Directory"` to the `Sidebar` section in both `messages/en.json` and `messages/ar.json`.

- [ ] **Step 5: Add i18n strings**

Add to `messages/en.json`:
```json
"AgentDirectory": {
  "heading": "Agent Directory",
  "subtitle": "{count, plural, one {# agent} other {# agents}} registered",
  "loading": "Loading...",
  "notFound": "Project not found",
  "searchPlaceholder": "Search capabilities... (e.g. 'review', 'testing')",
  "searching": "Searching...",
  "noAgents": "No agents found"
}
```

Add the same section to `messages/ar.json` with Arabic translations:
```json
"AgentDirectory": {
  "heading": "دليل الوكلاء",
  "subtitle": "{count, plural, one {وكيل واحد} other {# وكلاء}} مسجلون",
  "loading": "جارٍ التحميل...",
  "notFound": "المشروع غير موجود",
  "searchPlaceholder": "ابحث عن القدرات... (مثل 'مراجعة'، 'اختبار')",
  "searching": "جارٍ البحث...",
  "noAgents": "لا يوجد وكلاء"
}
```

Add `"directory": "Directory"` to `Sidebar` in `en.json` and `"directory": "الدليل"` in `ar.json`.

- [ ] **Step 6: Verify dashboard builds**

Run: `cd dashboard && npm run build`
Expected: Build succeeds without errors.

- [ ] **Step 7: Commit**

```bash
git add dashboard/components/agent-directory.tsx \
  dashboard/app/[locale]/projects/[id]/directory/page.tsx \
  dashboard/components/sidebar.tsx \
  dashboard/lib/api.ts \
  dashboard/messages/en.json \
  dashboard/messages/ar.json
git commit -m "feat(dashboard): add Agent Directory view with capability search"
```

---

## Verification

- [ ] `pytest tests/ -v` — all 214+ tests green (existing + new).
- [ ] `GET /api/projects/{id}/agents` returns `structured_capabilities` field.
- [ ] `GET /api/projects/{id}/agents/match?need=review` returns only matching agents.
- [ ] Dashboard Agent Directory page loads and capability search works.
- [ ] Dashboard builds without errors (`npm run build`).
- [ ] Old-style flat capabilities still match (backward compat).
- [ ] i18n strings in both `en.json` and `ar.json`.