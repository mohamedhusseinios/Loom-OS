# Loom OS Post-Parity Roadmap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Source spec:** [docs/superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md](../superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md)
> **Detail policy:** Phase 1 (P0) is fully task-by-task / test-first because it is the next work to execute. Phases 2-3 are architecture-level outlines — **expand each feature into its own detailed plan (`docs/plans/`) when that phase begins.** Re-run the competitor analysis before starting Phase 3.

**Goal:** Ship the 9 post-parity suggestions (LLM extraction, relational queries, distribution, team mode, client SDK, agent discovery, benchmarks, plugins, framework integrations) without breaking Loom's local-first, single-process, filesystem-protocol moat.

**Architecture:** Extend the existing Python FastAPI daemon (`daemon/`) and Next.js dashboard (`dashboard/`). New capabilities are new modules inside the single daemon process or **separate optional packages** (SDK, framework integrations). Graphify stays the AST source of truth; LLM-extracted, non-AST edges live in a **sidecar store merged at query/render time** (Graphify rebuilds `graph.json` from source and would otherwise erase them).

**Tech Stack:** Python 3.11+ (FastAPI, uvicorn, aiosqlite, watchdog, numpy, sentence-transformers, pyyaml, graphifyy), TypeScript (Next.js 16, React 19, shadcn, Cytoscape), MCP (stdio). LLM backends optional: Ollama (default/local), OpenAI, Anthropic.

## Global Constraints

Copied verbatim from the spec — **every task implicitly includes these:**

- Single-process daemon — `loom start` stays the only run command. No Docker, Neo4j, external DB, or cloud service.
- Filesystem inbox protocol preserved — extend it; never replace it with a required SDK or auth gate. The raw-file path stays fully supported.
- Per-project isolation intact (and per-user sub-scopes for Team mode).
- Code-specific Graphify AST not diluted — LLM extraction and hybrid queries **enrich**, never replace, AST understanding.
- Every user-facing feature ships a dashboard surface.
- WebSocket stays push-not-poll — emit new events for every new state change.
- New optional dependencies must stay optional — the base `pip install loom-os` install must not require an LLM client.
- Existing test suite must stay green at the end of every phase; every new daemon module gets `tests/test_<module>.py`.

---

# PHASE 1 — P0 (Differentiators) — detailed

> Order is data-flow driven: **#1 (LLM extractor) → #2 (relational queries) → #3 (ship)**. #1 enriches the graph with edges that #2 traverses; #3 packages the result.

## Feature #1 — Production-ready LLM Extractor

**Why first:** closes the last extraction-quality gap and produces the enriched edges #2 consumes. Today `ExtractorPipeline`/`RegexExtractor` exist in `daemon/extractors.py` but are **not wired into the runtime** — `Router._handle_finding` never calls them. This feature implements `LLMExtractor` *and* wires the pipeline in.

### Task 1.1: `LLMExtractor` class with injectable, configurable backend

**Files:**
- Modify: `daemon/extractors.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `Extractor` (ABC, `async extract(self, text: str) -> list[ExtractedEntity]`), `ExtractedEntity(name, kind, confidence=0.5, context="", relationships=None)` — both already in `daemon/extractors.py`.
- Produces: `LLMExtractor(backend: str = "ollama", model: str | None = None, call_fn=None)` where `call_fn: Callable[[str], Awaitable[str]] | None` is an injectable async function returning the raw LLM text (lets tests run with no live model). `async extract(text) -> list[ExtractedEntity]`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_extractors.py
import pytest
from daemon.extractors import LLMExtractor, ExtractedEntity


@pytest.mark.asyncio
async def test_llm_extractor_parses_entities_from_injected_backend():
    # Fake backend returns the structured JSON we expect the prompt to elicit.
    async def fake_call(prompt: str) -> str:
        return (
            '{"entities": ['
            '{"name": "AuthService", "kind": "class", "confidence": 0.9,'
            ' "context": "handles login", "relationships": [["uses", "BcryptHasher"]]}'
            ']}'
        )

    extractor = LLMExtractor(backend="ollama", call_fn=fake_call)
    entities = await extractor.extract("AuthService handles login via BcryptHasher")

    assert len(entities) == 1
    assert isinstance(entities[0], ExtractedEntity)
    assert entities[0].name == "AuthService"
    assert entities[0].kind == "class"
    assert entities[0].confidence == 0.9
    assert ("uses", "BcryptHasher") in entities[0].relationships


@pytest.mark.asyncio
async def test_llm_extractor_degrades_to_empty_on_bad_json():
    async def bad_call(prompt: str) -> str:
        return "the model rambled instead of returning JSON"

    extractor = LLMExtractor(backend="ollama", call_fn=bad_call)
    assert await extractor.extract("anything") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extractors.py::test_llm_extractor_parses_entities_from_injected_backend -v`
Expected: FAIL with `ImportError: cannot import name 'LLMExtractor'`

- [ ] **Step 3: Write minimal implementation**

```python
# Add to daemon/extractors.py (after RegexExtractor, before ExtractorPipeline)
import json as _json
import os
from typing import Awaitable, Callable


_LLM_PROMPT = """You extract code/architecture entities from an engineering note.
Return ONLY minified JSON: {"entities": [{"name","kind","confidence","context","relationships"}]}
- kind is one of: class, function, module, pattern, interface, enum.
- confidence is 0.0-1.0.
- relationships is a list of [verb, target] pairs (may be empty).
NOTE:
%s
"""


class LLMExtractor(Extractor):
    """Extract entities via a configurable LLM backend (Ollama/OpenAI/Claude).

    The backend call is injectable (`call_fn`) so tests run with no live model.
    Any failure (no backend, network error, bad JSON) degrades to an empty list;
    ExtractorPipeline already swallows extractor exceptions, so extraction never
    blocks finding ingestion.
    """

    def __init__(
        self,
        backend: str = "ollama",
        model: str | None = None,
        call_fn: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.backend = os.getenv("LOOM_LLM_BACKEND", backend)
        self.model = os.getenv("LOOM_LLM_MODEL", model or "")
        self._call_fn = call_fn  # injected in tests; real backends wired in Task 1.2

    async def extract(self, text: str) -> list[ExtractedEntity]:
        call = self._call_fn
        if call is None:
            return []  # no backend configured -> degrade (regex still runs)
        try:
            raw = await call(_LLM_PROMPT % text[:4000])
            data = _json.loads(raw)
        except Exception:
            return []
        return self._to_entities(data)

    @staticmethod
    def _to_entities(data: dict) -> list[ExtractedEntity]:
        out: list[ExtractedEntity] = []
        for item in data.get("entities", []):
            if not item.get("name") or not item.get("kind"):
                continue
            rels = [tuple(r) for r in item.get("relationships", []) if len(r) == 2]
            out.append(ExtractedEntity(
                name=str(item["name"]),
                kind=str(item["kind"]),
                confidence=float(item.get("confidence", 0.5)),
                context=str(item.get("context", "")),
                relationships=rels,
            ))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extractors.py -v`
Expected: PASS (new tests + existing regex/pipeline tests)

- [ ] **Step 5: Commit**

```bash
git add daemon/extractors.py tests/test_extractors.py
git commit -m "feat(extractors): add LLMExtractor with injectable backend + graceful degradation"
```

### Task 1.2: Wire real backends (Ollama default, OpenAI, Claude) behind the injectable seam

**Files:**
- Modify: `daemon/extractors.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Produces: `LLMExtractor._default_call(prompt: str) -> str` used when `call_fn is None` but a backend is configured/available. Resolves backend from `self.backend`. Keeps all three client imports **lazy** (optional deps).

- [ ] **Step 1: Write the failing test** (backend dispatch chooses the right client; no network in test)

```python
# Add to tests/test_extractors.py
@pytest.mark.asyncio
async def test_llm_extractor_unknown_backend_degrades():
    extractor = LLMExtractor(backend="does-not-exist")  # no call_fn injected
    # No client available -> extract returns [] rather than raising.
    assert await extractor.extract("AuthService handles login") == []
```

- [ ] **Step 2: Run test to verify behavior**

Run: `pytest tests/test_extractors.py::test_llm_extractor_unknown_backend_degrades -v`
Expected: PASS already (call_fn is None -> []), confirming the safe default before adding real calls.

- [ ] **Step 3: Implement `_default_call` with lazy, optional client imports**

```python
# In daemon/extractors.py, modify LLMExtractor.extract to fall back to _default_call:
    async def extract(self, text: str) -> list[ExtractedEntity]:
        call = self._call_fn or self._default_call
        try:
            raw = await call(_LLM_PROMPT % text[:4000])
            data = _json.loads(raw)
        except Exception as exc:
            logger.debug("LLMExtractor degraded (%s): %s", self.backend, exc)
            return []
        return self._to_entities(data)

    async def _default_call(self, prompt: str) -> str:
        """Call the configured backend. All client imports are lazy/optional."""
        if self.backend == "ollama":
            import httpx  # part of dev deps; ollama exposes HTTP on 11434
            model = self.model or "llama3.1"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": model, "prompt": prompt, "format": "json", "stream": False},
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
        if self.backend == "openai":
            from openai import AsyncOpenAI  # optional dep
            client = AsyncOpenAI()
            r = await client.chat.completions.create(
                model=self.model or "gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            return r.choices[0].message.content or ""
        if self.backend in ("claude", "anthropic"):
            from anthropic import AsyncAnthropic  # optional dep
            client = AsyncAnthropic()
            r = await client.messages.create(
                model=self.model or "claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        raise RuntimeError(f"unknown LLM backend: {self.backend}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_extractors.py -v`
Expected: PASS (degrade-on-missing-client path is covered; live calls are not exercised in CI)

- [ ] **Step 5: Commit**

```bash
git add daemon/extractors.py tests/test_extractors.py
git commit -m "feat(extractors): wire Ollama/OpenAI/Claude backends behind lazy optional imports"
```

### Task 1.3: `ExtractedEdgeStore` sidecar (persist non-AST edges per project)

**Files:**
- Create: `daemon/extracted_store.py`
- Test: `tests/test_extracted_store.py`

**Interfaces:**
- Produces: `ExtractedEdgeStore(loom_dir: str | None = None)` with `add(project: str, source_file: str, entities: list[ExtractedEntity]) -> None` and `load(project: str) -> list[dict]` (each dict: `{name, kind, confidence, context, relationships, source_file, source: "llm"}`). Stored at `~/.loom/extracted/<project>.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extracted_store.py
import pytest
from daemon.extracted_store import ExtractedEdgeStore
from daemon.extractors import ExtractedEntity


@pytest.mark.asyncio
async def test_add_and_load_extracted_edges(tmp_path):
    store = ExtractedEdgeStore(loom_dir=str(tmp_path))
    ents = [ExtractedEntity(name="AuthService", kind="class", confidence=0.9,
                            relationships=[("uses", "BcryptHasher")])]
    await store.add("proj-1", "finding-abc.md", ents)

    rows = await store.load("proj-1")
    assert len(rows) == 1
    assert rows[0]["name"] == "AuthService"
    assert rows[0]["source"] == "llm"
    assert rows[0]["source_file"] == "finding-abc.md"
    assert rows[0]["relationships"] == [["uses", "BcryptHasher"]]


@pytest.mark.asyncio
async def test_load_missing_project_returns_empty(tmp_path):
    store = ExtractedEdgeStore(loom_dir=str(tmp_path))
    assert await store.load("nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extracted_store.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```python
# daemon/extracted_store.py
"""Sidecar store for LLM-extracted, non-AST graph edges.

Graphify rebuilds graph.json from source AST on every build, which would erase
LLM-derived edges. We persist them separately (per project) and merge at
query/render time. JSON is sufficient for V1 (<10K edges), matching Loom's
zero-infra philosophy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from daemon.extractors import ExtractedEntity


class ExtractedEdgeStore:
    def __init__(self, loom_dir: str | None = None):
        self.base = Path(loom_dir or os.path.expanduser("~/.loom")) / "extracted"

    def _path(self, project: str) -> Path:
        return self.base / f"{project}.json"

    async def add(self, project: str, source_file: str, entities: list[ExtractedEntity]) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        rows = await self.load(project)
        for e in entities:
            rows.append({
                "name": e.name,
                "kind": e.kind,
                "confidence": e.confidence,
                "context": e.context,
                "relationships": [list(r) for r in e.relationships],
                "source_file": source_file,
                "source": "llm",
            })
        self._path(project).write_text(json.dumps(rows, indent=2))

    async def load(self, project: str) -> list[dict]:
        p = self._path(project)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extracted_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/extracted_store.py tests/test_extracted_store.py
git commit -m "feat: add ExtractedEdgeStore sidecar for LLM-derived non-AST edges"
```

### Task 1.4: Wire `ExtractorPipeline` into `Router._handle_finding`

**Files:**
- Modify: `daemon/router.py:32-42` (constructor) and `daemon/router.py:121-143` (`_handle_finding`)
- Modify: `daemon/api.py` (lifespan — assemble pipeline + store and pass to Router)
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `ExtractorPipeline` (`.add(extractor)`, `async run(text) -> list[ExtractedEntity]`), `ExtractedEdgeStore.add(...)`, `RegexExtractor`, `LLMExtractor`.
- Produces: `Router.__init__(..., extractor_pipeline: ExtractorPipeline | None = None, extracted_store: ExtractedEdgeStore | None = None)`. On a finding, runs the pipeline over the finding body and persists results; emits `extraction:completed`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_router.py
import pytest
from daemon.router import Router
from daemon.extractors import ExtractorPipeline, RegexExtractor
from daemon.extracted_store import ExtractedEdgeStore


@pytest.mark.asyncio
async def test_finding_runs_extractor_pipeline_and_persists(tmp_path, monkeypatch):
    # Minimal registry/graph doubles: handler only needs get_project to return None
    class _Reg:
        async def get_project(self, p): return None
    class _Graph:
        available = False

    pipeline = ExtractorPipeline()
    pipeline.add(RegexExtractor())
    store = ExtractedEdgeStore(loom_dir=str(tmp_path))

    router = Router(registry=_Reg(), graph_engine=_Graph(),
                    extractor_pipeline=pipeline, extracted_store=store)

    finding = tmp_path / "finding-x.md"
    finding.write_text("---\nagent: a\nproject: proj-1\n---\nThe AuthService class uses a Repository pattern.")

    await router._handle_finding("proj-1", finding)

    rows = await store.load("proj-1")
    assert any(r["name"] == "AuthService" for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_router.py::test_finding_runs_extractor_pipeline_and_persists -v`
Expected: FAIL — `Router.__init__() got an unexpected keyword argument 'extractor_pipeline'`

- [ ] **Step 3: Implement constructor + handler wiring**

```python
# daemon/router.py — extend __init__ signature and store the new deps
    def __init__(
        self,
        registry: AgentRegistry,
        graph_engine: GraphEngine,
        recall: RecallEngine | None = None,
        extractor_pipeline=None,        # ExtractorPipeline | None
        extracted_store=None,           # ExtractedEdgeStore | None
    ):
        self.registry = registry
        self.graph = graph_engine
        self.recall = recall
        self.extractor_pipeline = extractor_pipeline
        self.extracted_store = extracted_store
        self._last_update: dict[str, float] = {}
        self._event_queue: asyncio.Queue[WsEvent] = asyncio.Queue()
```

```python
# daemon/router.py — in _handle_finding, after _emit_event("finding:ingested", ...)
        # Run knowledge extraction (regex + optional LLM) and persist edges.
        if self.extractor_pipeline is not None and self.extracted_store is not None:
            body = content.split("---", 2)[-1] if content.startswith("---") else content
            try:
                entities = await self.extractor_pipeline.run(body)
                if entities:
                    await self.extracted_store.add(project, path.name, entities)
                    await self._emit_event("extraction:completed", project, {
                        "file": path.name, "entities": len(entities),
                    })
            except Exception as exc:
                logger.warning("Extraction failed for %s: %s", path.name, exc)
```

- [ ] **Step 4: Assemble the pipeline in `api.py` lifespan and run tests**

```python
# daemon/api.py — where Router is constructed in lifespan (non-test mode),
# build the pipeline + store and pass them in:
from daemon.extractors import ExtractorPipeline, RegexExtractor, LLMExtractor
from daemon.extracted_store import ExtractedEdgeStore

_pipeline = ExtractorPipeline()
_pipeline.add(RegexExtractor())          # always-on, wins dedup ties
_pipeline.add(LLMExtractor())            # degrades to [] if no backend
_extracted_store = ExtractedEdgeStore()
router = Router(registry, graph_engine, recall=recall,
                extractor_pipeline=_pipeline, extracted_store=_extracted_store)
```

Run: `pytest tests/test_router.py tests/test_api.py -v`
Expected: PASS (new test + existing router/api tests stay green)

- [ ] **Step 5: Commit**

```bash
git add daemon/router.py daemon/api.py tests/test_router.py
git commit -m "feat(router): run extractor pipeline on findings and persist extracted edges"
```

### Task 1.5: API endpoint to expose extracted edges

**Files:**
- Modify: `daemon/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `GET /api/projects/{project_id}/extracted-edges` → `{"edges": [<row>, ...]}` from `ExtractedEdgeStore.load(project_id)`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py (follows the module-global test pattern: assign api_module.* before TestClient)
def test_extracted_edges_endpoint_empty(client):
    resp = client.get("/api/projects/proj-1/extracted-edges")
    assert resp.status_code == 200
    assert resp.json() == {"edges": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_extracted_edges_endpoint_empty -v`
Expected: FAIL — 404 (route not defined)

- [ ] **Step 3: Implement endpoint**

```python
# daemon/api.py — add near the other project read endpoints
from daemon.extracted_store import ExtractedEdgeStore

@app.get("/api/projects/{project_id}/extracted-edges")
async def get_extracted_edges(project_id: str):
    """Return LLM-extracted (non-AST) edges for overlay on the graph."""
    store = ExtractedEdgeStore()
    return {"edges": await store.load(project_id)}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat(api): expose extracted-edges endpoint for graph overlay"
```

### Task 1.6: Dashboard — render extracted edges with dashed style

**Files:**
- Modify: `dashboard/components/graph-canvas.tsx` (Cytoscape edge style + fetch/merge)
- Modify: `dashboard/lib/api.ts` (typed fetch for extracted edges) if a helper is used there

**Interfaces:**
- Consumes: `GET /api/projects/{id}/extracted-edges` → `{ edges: { name, kind, relationships, confidence, source }[] }`.

- [ ] **Step 1: Add a Cytoscape style for LLM edges**

In `graph-canvas.tsx`, add a selector to the stylesheet so edges tagged `data(source) === "llm"` render dashed and dimmer:

```ts
{
  selector: 'edge[source = "llm"]',
  style: {
    'line-style': 'dashed',
    'line-color': '#6366f1',     // indigo, distinct from AST edges
    'target-arrow-color': '#6366f1',
    'opacity': 0.7,
  },
},
```

- [ ] **Step 2: Fetch extracted edges and merge into the graph elements**

After the existing topology fetch, fetch `/api/projects/${projectId}/extracted-edges`, map each `relationship [verb, target]` into a Cytoscape edge with `data: { source: "llm", label: verb }`, and concat into the elements array before `cy.add(...)`. Skip edges whose endpoints aren't present as nodes (add lightweight nodes for missing targets).

- [ ] **Step 3: Manual verification**

Run the daemon + dashboard, drop a `finding-*.md` that references a class, confirm a dashed indigo edge appears on the graph and the count matches `/extracted-edges`. (No unit test — visual component.)

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/graph-canvas.tsx dashboard/lib/api.ts
git commit -m "feat(dashboard): overlay LLM-extracted edges with dashed style"
```

---

## Feature #2 — Relational query support (graph + vector + relational)

**Why second:** consumes #1's extracted edges. Today `registry.hybrid_search` (registry.py:369 → api.py:853) does **text + vector over findings only** — no graph traversal. This feature adds a graph-aware hybrid planner.

### Task 2.1: `GraphEngine.hybrid_query` — vector-seeded graph BFS

**Files:**
- Modify: `daemon/graph_engine.py`
- Test: `tests/test_graph_engine.py`

**Interfaces:**
- Consumes: `GraphEngine._read_graph_json(path) -> dict` (static, graph_engine.py:110), `EmbeddingGenerator().embed(text) -> list[float]` (daemon/embeddings.py), `ExtractedEdgeStore.load(project) -> list[dict]`.
- Produces: `async hybrid_query(self, project_path: str, project: str, question: str, depth: int = 2, top_k: int = 10) -> list[dict]` returning rows `{id, kind, semantic_score, structural_distance}` sorted by a blended rank.

- [ ] **Step 1: Write the failing test** (uses a hand-written graph.json so no Graphify subprocess is needed)

```python
# tests/test_graph_engine.py
import json
import pytest
from daemon.graph_engine import GraphEngine


@pytest.mark.asyncio
async def test_hybrid_query_returns_dual_relevance(tmp_path, monkeypatch):
    # Minimal graph.json with two connected nodes.
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps({
        "nodes": [{"id": "AuthService", "kind": "class"},
                  {"id": "BcryptHasher", "kind": "class"}],
        "edges": [{"source": "AuthService", "target": "BcryptHasher", "kind": "uses"}],
    }))

    # Deterministic embedding: vector = [len(text)] so 'AuthService' seeds first.
    async def fake_embed(self, text):
        return [float(len(text)), 1.0]
    monkeypatch.setattr("daemon.embeddings.EmbeddingGenerator.embed", fake_embed, raising=False)

    engine = GraphEngine()
    rows = await engine.hybrid_query(str(tmp_path), "proj-1", "AuthService", depth=1)

    ids = [r["id"] for r in rows]
    assert "AuthService" in ids                       # vector seed
    assert "BcryptHasher" in ids                      # reached via BFS
    bcrypt = next(r for r in rows if r["id"] == "BcryptHasher")
    assert bcrypt["structural_distance"] == 1
    assert "semantic_score" in bcrypt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph_engine.py::test_hybrid_query_returns_dual_relevance -v`
Expected: FAIL — `AttributeError: 'GraphEngine' object has no attribute 'hybrid_query'`

- [ ] **Step 3: Implement `hybrid_query`**

```python
# daemon/graph_engine.py — add to GraphEngine
import math
from pathlib import Path
from daemon.embeddings import EmbeddingGenerator
from daemon.extracted_store import ExtractedEdgeStore

    async def hybrid_query(self, project_path: str, project: str, question: str,
                           depth: int = 2, top_k: int = 10) -> list[dict]:
        """Vector-seed the graph, then BFS along AST + extracted edges.

        Returns rows carrying BOTH semantic (cosine) and structural (BFS depth)
        relevance — the graph+vector(+relational) join Cognee charges for.
        """
        graph = self._read_graph_json(Path(project_path) / "graphify-out" / "graph.json")
        nodes = {n.get("id") or n.get("name"): n for n in graph.get("nodes", [])}
        adj: dict[str, list[str]] = {}
        for e in graph.get("edges", []):
            adj.setdefault(e.get("source"), []).append(e.get("target"))
        # Merge extracted (relational) edges so the join spans non-AST links too.
        for row in await ExtractedEdgeStore().load(project):
            for _verb, target in row.get("relationships", []):
                adj.setdefault(row["name"], []).append(target)

        gen = EmbeddingGenerator()
        q_vec = await gen.embed(question)
        # Seed: cosine similarity of question vs each node id/label.
        seeds: list[tuple[str, float]] = []
        for nid in nodes:
            score = self._cosine(q_vec, await gen.embed(str(nid)))
            seeds.append((nid, score))
        seeds.sort(key=lambda s: s[1], reverse=True)

        # BFS from top seeds, recording structural distance.
        results: dict[str, dict] = {}
        from collections import deque
        for nid, sem in seeds[:max(3, top_k // 2)]:
            dq = deque([(nid, 0)])
            seen = {nid}
            while dq:
                cur, dist = dq.popleft()
                if cur not in results:
                    results[cur] = {
                        "id": cur,
                        "kind": (nodes.get(cur) or {}).get("kind", "unknown"),
                        "semantic_score": self._cosine(q_vec, await gen.embed(str(cur))),
                        "structural_distance": dist,
                    }
                if dist < depth:
                    for nxt in adj.get(cur, []):
                        if nxt not in seen:
                            seen.add(nxt)
                            dq.append((nxt, dist + 1))

        ranked = sorted(
            results.values(),
            key=lambda r: (r["semantic_score"] - 0.1 * r["structural_distance"]),
            reverse=True,
        )
        return ranked[:top_k]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb + 1e-8)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_graph_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/graph_engine.py tests/test_graph_engine.py
git commit -m "feat(graph): add hybrid_query — vector-seeded BFS over AST + extracted edges"
```

### Task 2.2: API `hybrid` mode + dashboard toggle

**Files:**
- Modify: `daemon/api.py` (extend search route with `mode=hybrid`), `tests/test_api.py`
- Modify: `dashboard/components/search-bar.tsx` (mode toggle), `dashboard/components/graph-canvas.tsx` (optional path highlight)

**Interfaces:**
- Consumes: `GraphEngine.hybrid_query(project_path, project, question)`, `registry.get_project(project) -> project_info` (for `project_path`).
- Produces: `GET /api/projects/{project_id}/search?q=...&mode=hybrid` → `{"results": [...], "mode": "hybrid"}`. `mode` defaults to existing text+vector behavior.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_search_hybrid_mode(client, monkeypatch):
    async def fake_hybrid(self, project_path, project, question, **kw):
        return [{"id": "AuthService", "kind": "class",
                 "semantic_score": 0.9, "structural_distance": 0}]
    monkeypatch.setattr("daemon.graph_engine.GraphEngine.hybrid_query", fake_hybrid)
    resp = client.get("/api/projects/proj-1/search?q=auth&mode=hybrid")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "hybrid"
    assert body["results"][0]["id"] == "AuthService"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_search_hybrid_mode -v`
Expected: FAIL — current route ignores `mode` / has no `mode` key

- [ ] **Step 3: Extend the search route**

```python
# daemon/api.py — modify the existing GET /api/projects/{project_id}/search
@app.get("/api/projects/{project_id}/search")
async def hybrid_search(project_id: str, q: str = "", mode: str = "text"):
    if not q:
        return {"results": [], "mode": mode}
    if mode == "hybrid":
        project = await registry.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        results = await graph_engine.hybrid_query(project.project_path, project_id, q)
        return {"results": results, "mode": "hybrid"}
    results = await registry.hybrid_search(project_id, q)   # existing text+vector
    return {"results": results, "mode": "text"}
```

- [ ] **Step 4: Add the dashboard toggle**

In `search-bar.tsx`, add a `mode` state (`"text" | "hybrid"`) with a small toggle, pass `&mode=${mode}` on the request, and render `structural_distance` + `semantic_score` when present.

- [ ] **Step 5: Run tests + commit**

Run: `pytest tests/test_api.py -v` → Expected: PASS

```bash
git add daemon/api.py dashboard/components/search-bar.tsx tests/test_api.py
git commit -m "feat: hybrid search mode (graph+vector+relational) with dashboard toggle"
```

---

## Feature #3 — Ship to users (PyPI, docs, quickstart)

**Why third:** packages the now feature-complete daemon. Mostly metadata + docs; CLI gets `loom init`.

### Task 3.1: Fill `pyproject.toml` release metadata

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace `[project]` metadata** with PyPI-ready fields

```toml
[project]
name = "loom"
version = "0.2.0"
description = "Loom OS — unified agent memory fabric for multi-agent coding"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
keywords = ["ai-agents", "knowledge-graph", "agent-memory", "mcp", "code-graph"]
authors = [{ name = "Mohamed Hussien" }]
classifiers = [
  "Development Status :: 4 - Beta",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Topic :: Software Development :: Libraries",
]
# dependencies unchanged

[project.urls]
Homepage = "https://github.com/mohamedhusseinios/Loom-OS"
Repository = "https://github.com/mohamedhusseinios/Loom-OS"
Issues = "https://github.com/mohamedhusseinios/Loom-OS/issues"

[project.optional-dependencies]
llm = ["openai>=1.0", "anthropic>=0.39", "httpx>=0.27"]   # optional LLM backends (#1)
dev = ["pytest>=8.0", "pytest-asyncio>=0.24.0", "httpx>=0.27.0"]
```

- [ ] **Step 2: Verify the build**

Run: `python -m build` (after `pip install build`)
Expected: `dist/loom-0.2.0-py3-none-any.whl` + sdist produced, no metadata errors

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: PyPI-ready metadata, version 0.2.0, optional [llm] extra"
```

### Task 3.2: `loom init` CLI command

**Files:**
- Modify: `daemon/main.py` (add `cmd_init`, parser, `KNOWN_SUBCOMMANDS`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `loom init [--project NAME] [--project-path PATH]` — creates `~/.loom/inbox/<project>/`, writes a starter `register.json`, prints next steps. Reuses the `cmd_register` payload shape.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json, os
from daemon.main import cmd_init
from types import SimpleNamespace


def test_init_scaffolds_inbox_and_register(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cmd_init(SimpleNamespace(project="demo", project_path=str(tmp_path),
                             agent="claude-code"))
    reg = tmp_path / ".loom" / "inbox" / "demo" / "register.json"
    assert reg.exists()
    assert json.loads(reg.read_text())["project"] == "demo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `cannot import name 'cmd_init'`

- [ ] **Step 3: Implement `cmd_init` + parser**

```python
# daemon/main.py — add the function
def cmd_init(args):
    """Bootstrap a project: create the inbox and a starter register.json."""
    inbox = os.path.expanduser(f"~/.loom/inbox/{args.project}")
    os.makedirs(inbox, exist_ok=True)
    payload = {
        "agent": args.agent, "version": "1.0", "project": args.project,
        "project_path": os.path.expanduser(args.project_path), "capabilities": [],
    }
    with open(os.path.join(inbox, "register.json"), "w") as f:
        json.dump(payload, f, indent=2)
    print(f"✓ Initialized Loom project '{args.project}'")
    print("  Next: run `loom start`, then open http://localhost:3000")
```

```python
# daemon/main.py — register the subcommand and add "init" to KNOWN_SUBCOMMANDS
    KNOWN_SUBCOMMANDS = {"start", "register", "unregister", "detect-agents", "worker", "init"}
    # ...
    init_p = sub.add_parser("init", help="Bootstrap a Loom project in the current directory")
    init_p.add_argument("--project", required=True, help="Project identifier")
    init_p.add_argument("--project-path", default=".", help="Path to the project (default: cwd)")
    init_p.add_argument("--agent", default="claude-code", help="Initial agent name")
    init_p.set_defaults(func=cmd_init)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/main.py tests/test_cli.py
git commit -m "feat(cli): add `loom init` to bootstrap a project"
```

### Task 3.3: Rewrite README + quickstart (reflect real capabilities)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite** the README with: one-paragraph pitch; the **naming note** (product "Loom OS" / package `loom-os` / CLI `loom` / repo `agentic-os`); a 5-step quickstart (`pip install loom-os` → `loom start` → `loom init --project X --project-path .` → `loom register ...` → open `http://localhost:3000`); a capability list that matches the code (remove the stale "Out of Scope (v1)" section — graph viz, dashboard dispatch, project CRUD all shipped); link the design specs and this roadmap.
- [ ] **Step 2: Verify** every command in the quickstart actually runs against a fresh checkout (manual).
- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README with accurate capabilities + quickstart"
```

### Task 3.4: Publish to TestPyPI, then PyPI

**Files:** none (release process)

- [ ] **Step 1:** `python -m build` → **Step 2:** `twine upload --repository testpypi dist/*` → **Step 3:** in a clean venv, `pip install -i https://test.pypi.org/simple/ loom` and run `loom --help` + `loom start` smoke test → **Step 4:** on success, `twine upload dist/*` to real PyPI → **Step 5:** tag the release `git tag v0.2.0 && git push --tags`.

> **Phase 1 done when:** `pip install loom-os` works from PyPI; `loom init` bootstraps; findings produce confidence-scored extracted edges (dashed in the dashboard, degrading to regex with no LLM backend); `?mode=hybrid` search returns dual-relevance results.

---

# PHASE 2 — P1 (High Upside) — architecture-level

> **Expand each feature below into its own detailed `docs/plans/` plan (TDD, bite-sized) when Phase 2 begins.** Outlines give objective, files, interfaces, key steps, and verification — enough to scope and sequence, not yet to execute line-by-line.

## Feature #4 — Team mode (shared daemon, multi-user)

- **Objective:** run one daemon for several developers behind **opt-in** auth, with per-user inbox isolation. Local single-process stays the default (auth off).
- **Files:** `daemon/main.py` (`start` gains `--auth-token`; `--host 0.0.0.0` already supported), new `daemon/auth.py` (token middleware), `daemon/watcher.py` + `daemon/router.py` (parse `<project>/<user>/` inbox sub-paths), `daemon/registry.py` (add `user` column to agents), `daemon/shared_context.py` (aggregate cross-user findings), `dashboard/` (team view + auth header), `tests/test_auth.py`.
- **Interfaces:** `auth.require_token(request)` FastAPI dependency, no-op when no token configured; inbox path parser `parse_inbox_path(path) -> (project, user, filename)`.
- **Key steps:** (1) token middleware as an optional dependency on write routes + `/ws`; (2) extend watcher path extraction to capture `user`; (3) per-user inbox dirs `~/.loom/inbox/<project>/<user>/`; (4) registry `user` scoping; (5) cross-user `SHARED_CONTEXT.md`; (6) dashboard team view.
- **Verification:** with no token, every existing test passes unchanged (moat); with a token, unauthenticated writes get 401; two users' findings appear in one shared context; WS event `team:agent_joined` emitted.
- **Risks:** auth must be strictly opt-in; shared filesystem (NFS/Syncthing) is a documented deployment assumption, not built.

## Feature #5 — Client SDK (`loom-client`, py + npm)

- **Objective:** one-liners for the inbox protocol with schema validation; the raw-file path stays fully supported.
- **Files:** new top-level `loom-client/` (separate package: `pyproject.toml`, `loom_client/__init__.py`, `client.py`), `loom-client/tests/`, plus `clients/js/` (npm: `package.json`, `src/index.ts`). Reuse schemas from `daemon/models.py` as the source of truth.
- **Interfaces:** `LoomClient(loom_dir=None)` → `register(project, agent, capabilities=...)`, `heartbeat(project, agent)`, `finding(project, agent, title, body, files=...)`, `task(project, title, instruction, assignee=...)`. Each validates with Pydantic and writes to the correct inbox path/filename.
- **Key steps:** (1) port the file-naming + payload shapes from `daemon/main.py` + `daemon/models.py`; (2) Pydantic validation; (3) examples for Claude Code / shell / Python; (4) npm twin mirroring the API; (5) publish both packages alongside #3's release pipeline.
- **Verification:** SDK-written files are byte-compatible with hand-written ones (round-trip test: write via SDK → daemon processes it → agent appears online); npm package `loom.finding(...)` produces an identical file.
- **Risks:** schema drift — pin the SDK's models to the daemon's; add a CI check that compares them.

## Feature #6 — Agent discovery / directory

- **Objective:** agents and humans can see who is on a project and what they can do; capability matching. Builds on the **existing** registry (`AgentInfo`, `list_agents_by_project`, `register` already takes `capabilities`).
- **Files:** `daemon/models.py` (richer `AgentCapability` schema `{name, description, tools, models, status}`), `daemon/api.py` (`GET /api/projects/{id}/agents` capability view + `GET .../agents/match?need=review`), `daemon/registry.py` (store/serve structured capabilities), `dashboard/components/agent-directory.tsx`, `tests/test_api.py`.
- **Interfaces:** `GET /api/projects/{id}/agents` → `[{agent_id, name, capabilities[], status, last_activity}]`; `registry.match_capability(project, need) -> list[AgentInfo]`.
- **Key steps:** (1) extend capability schema (backward-compatible with the current comma-string capabilities); (2) capability-listing endpoint; (3) simple keyword match endpoint; (4) "Agent Directory" dashboard view with status + recent activity.
- **Verification:** registering two agents with different capabilities lists both; `match?need=review` returns only the reviewer; existing agent tests stay green.
- **Risks:** low — mostly additive over existing data.

> **Phase 2 done when:** daemon runs multi-user behind optional auth with per-user isolation; `loom-client` (py + npm) is published with examples; the Agent Directory lists capabilities and supports matching.

---

# PHASE 3 — P2 (Future Advantage) — architecture-level

> **Re-run the competitor analysis before starting Phase 3** (the category moves fast). Then expand each feature into its own detailed plan.

## Feature #7 — Performance benchmarks & optimization

- **Objective:** prove single-process/SQLite/NumPy beats Docker+Neo4j; make it marketing-grade. Run **after** #1/#2 so it measures the real retrieval stack.
- **Files:** new `benchmarks/` (`harness.py`, `datasets/`, `report.py`), targeted optimization in `daemon/graph_engine.py` (cache `_read_graph_json` per mtime; reuse Graphify subprocess where possible), `daemon/embeddings.py` (batch `embed`).
- **Interfaces:** `harness.run(repo_path) -> {recall_precision, query_latency_ms, build_time_s}`.
- **Key steps:** (1) ingest a large repo; (2) measure recall precision, query latency, build time; (3) compare vs. Cognee/Graphiti on equivalent tasks; (4) optimize measured hot paths; (5) publish a comparison page.
- **Verification:** harness is reproducible; a graph.json cache invalidates on file mtime change (no stale data); latency improves vs. a pre-optimization baseline captured in step 1.

## Feature #9 — Plugin system for extractors & ingestors

- **Objective:** community-contributed extractors via the **existing** `Extractor` ABC, now a public contract. Builds on #1's matured pipeline.
- **Files:** `daemon/extractors.py` (documented public contract), new `daemon/plugins.py` (discovery/loader), `daemon/api.py` lifespan (load on startup), `~/.loom/plugins/extractors/`, example plugins under `examples/plugins/`, `tests/test_plugins.py`.
- **Interfaces:** each plugin file exposes `def register() -> Extractor`; `plugins.discover(loom_dir) -> list[Extractor]` added to the `ExtractorPipeline` after the built-ins.
- **Key steps:** (1) define + document the contract; (2) startup discovery of `~/.loom/plugins/extractors/<name>.py`; (3) add discovered extractors to the pipeline; (4) ship 2-3 examples (Python patterns, Git history, TODO scanner); (5) dashboard list + enable/disable.
- **Verification:** a dropped-in example plugin is discovered and its entities appear in `extracted-edges`; a broken plugin is skipped with a warning (pipeline already swallows extractor exceptions).
- **Risks:** plugins run in-process — document the trust boundary (local plugins only; no remote auto-install in v1).

## Feature #10 — LangChain / LlamaIndex / CrewAI integrations

- **Objective:** discoverability in the largest agent ecosystem. Wrap #5's SDK (land **after** #5) rather than re-implementing file I/O three times.
- **Files:** new separate packages `integrations/langchain-loom/`, `integrations/llama-index-loom/`, `integrations/crewai-loom/`, each with its own `pyproject.toml` + tests + README.
- **Interfaces:** `langchain-loom` implements LangChain `BaseMemory` (`load_memory_variables`, `save_context`); `llama-index-loom` a storage backend; `crewai-loom` shared crew memory — all delegating to `loom-client`.
- **Key steps:** one package per integration (~1 week each), thin wrapper over the SDK/REST, with a runnable example each.
- **Verification:** each integration's example round-trips a memory write/read through a running daemon; no daemon changes required.
- **Risks:** keep them thin; pin to `loom-client` to avoid duplicating protocol logic.

> **Phase 3 done when:** a published benchmark comparison exists; ≥2 example extractor plugins auto-discover; ≥1 framework integration (LangChain) is published.

---

## Verification Checklist (every phase)

- [ ] Existing test suite green after each phase (run `pytest tests/ -v`).
- [ ] No new **required** infrastructure (no Docker/Neo4j/external DB/cloud). New LLM deps live behind the `[llm]` extra.
- [ ] Filesystem inbox protocol preserved; raw-file path still works without the SDK.
- [ ] Single-process daemon — `loom start` remains the only run command.
- [ ] Per-project (and, in Phase 2, per-user) isolation intact.
- [ ] Each new daemon module has `tests/test_<module>.py`.
- [ ] WebSocket events emitted for new state changes (`extraction:completed`, `team:agent_joined`, …).
- [ ] Every user-facing feature ships a dashboard surface.
- [ ] Graphify's own `graph.json` output is never broken; extracted edges live in the sidecar and merge at query/render time.

## Summary

| Phase | Features | Detail level | New files | Modified files |
|-------|----------|--------------|-----------|----------------|
| **1 — P0** | #1 LLM extractor · #2 Relational · #3 Ship | Full TDD, task-by-task | `extracted_store.py`, `tests/test_extracted_store.py`, `tests/test_graph_engine.py`, `tests/test_cli.py` | `extractors.py`, `router.py`, `api.py`, `graph_engine.py`, `main.py`, `pyproject.toml`, `README.md`, dashboard `graph-canvas.tsx`, `search-bar.tsx` |
| **2 — P1** | #4 Team mode · #5 SDK · #6 Agent discovery | Architecture outline → expand per feature | `auth.py`, `loom-client/`, `clients/js/`, `agent-directory.tsx` | `main.py`, `watcher.py`, `router.py`, `registry.py`, `models.py`, `shared_context.py`, `api.py` |
| **3 — P2** | #7 Benchmarks · #9 Plugins · #10 Integrations | Architecture outline → expand per feature | `benchmarks/`, `plugins.py`, `integrations/*` | `graph_engine.py`, `embeddings.py`, `extractors.py`, `api.py` |

## Next Steps

1. Execute Phase 1 task-by-task (subagent-driven recommended). It is the launch-enabling phase.
2. When Phase 2 starts, expand #4/#5/#6 into individual detailed plans under `docs/plans/`.
3. Re-run the competitor analysis before Phase 3; adjust #7/#9/#10 to the then-current landscape.
