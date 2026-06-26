# Architecture/Design Plan Inputs: Agentic OS

> Generated 2026-06-26 from the competitor analysis
>
> Load the `writing-plans` or `plan` skill with this file as context to generate the full implementation plan.

## Project Context

- **Name:** Agentic OS
- **One-line description:** Unified agent memory fabric — a single-machine daemon linking all AI coding agents through a shared Graphify-powered knowledge graph, with a Next.js dashboard control plane.
- **Category:** Agent memory fabric / knowledge graph platform
- **Platform:** Local machine (macOS/Linux), Python daemon + Next.js dashboard
- **Target market:** Developers running multiple AI coding agents (Claude Code, Codex, Hermes) who want shared memory across agents
- **Tech stack:**
  - Python 3.11+ FastAPI daemon (uvicorn)
  - SQLite (aiosqlite) for agent registry
  - Graphify (in-process) for code knowledge graph extraction
  - Watchdog for filesystem inbox monitoring
  - Next.js 15 App Router + Shadcn UI + Tailwind CSS dashboard
  - WebSocket for live event streaming
- **Current status:** v0.1.0 — daemon + dashboard working, 22 tests passing. Three new features in active design: Project CRUD, Graph Visual Explorer (Cytoscape.js), Agent Management & Wiring.

---

## Competitive Constraints (from analysis)

### CRITICAL features (define the category — without these, Agentic OS is not a memory fabric)

| # | Feature | Why existential |
|---|---------|----------------|
| 1 | **Shared cross-agent memory bank (auto-recall + auto-retain)** | Claude Code sub-agents forget everything between sessions. Hindsight proved auto-recall/retain compounds agent intelligence. Cognee has session→permanent bridging. Without this, Agentic OS is a file system with a graph index. |
| 2 | **Durable multi-agent task board with lifecycle** | Hermes Kanban has 7-state lifecycle + crash recovery + dependency management. Agentic OS inbox protocol is "write a file, hope an agent picks it up." Agents need coordination, not just memory. |

### Must-have features (P0 — category gaps to fill)

| # | Feature | Why table-stakes |
|---|---------|------------------|
| 3 | **Hybrid vector-graph retrieval** | Cognee benchmarks 0.93 correctness with vector→graph vs 0.4 for base RAG. OpenClaw combines BM25+vector+MMR. Agentic OS has FTS5 text-only — can't answer semantic queries like "what do we know about auth?" |
| 4 | **LLM-powered auto knowledge extraction** | Graphiti auto-extracts entities/edges from unstructured text (94.8% DMR, 18.5% LongMemEval improvement). Agentic OS requires manual YAML frontmatter — findings could auto-enrich the graph. |
| 5 | **Session memory with context continuity** | Cognee has pronoun resolution across turns ("Where does Alice live?" → "What does *she* do?"). Agentic OS has project isolation but no session-level context continuity. |

### Quality bars to meet or exceed

- **Dashboard parity with LangGraph Studio:** Agentic OS's dashboard must be at least as good as LangGraph Studio for visual agent inspection
- **Semantic search parity with Cognee:** The query API must support semantic/embedding search, not just structural graph queries
- **Filesystem protocol simplicity:** The inbox protocol must remain the simplest possible integration — any change must preserve zero-SDK, zero-auth
- **Single-process commitment:** Must remain installable via `pip install` + single command. No Docker, no Neo4j, no external infrastructure

### What NOT to compromise (competitive moat)

| Moat | Reason |
|------|--------|
| Filesystem inbox protocol | The single biggest differentiator. No competitor has it. |
| Single-process daemon | Zero-infrastructure install. Cognee needs Docker + Neo4j. |
| Per-project isolation | Clean separation. Competitors are flat namespaces. |
| Code-specific (Graphify AST) | Understands code structure, not just text. |
| Dashboard control plane | No memory competitor has a UI. |

---

## Differentiation Strategy

- **Primary differentiator:** Filesystem inbox protocol — the simplest possible integration surface. Any tool can connect by writing a file. This is the "USB of agent memory."
- **Secondary differentiators:**
  - Single-process daemon (zero infrastructure)
  - Code-specific knowledge graph (Graphify AST extraction)
  - Dashboard control plane (no memory competitor has one)
  - Per-project isolation (clean separation)
  - WebSocket live updates (push, not poll)

---

## Architecture Implications

### Suggestion 1: Vector embedding search

| Component | Type | Effort |
|-----------|------|--------|
| `findings_embeddings` table (SQLite) or in-process ChromaDB | New | 0.5 day |
| `graph_engine.py::ingest_finding()` — add embedding step | Modify (~30 LOC) | 0.5 day |
| `GET /api/projects/:id/search?q=` endpoint | New (~40 LOC) | 0.5 day |
| `<SearchBar>` dashboard component | New (~100 LOC) | 0.5 day |
| Embedding model (sentence-transformers, OpenAI, or Ollama) | Config | 0.3 day |
| **Total** | | **~2-3 days** |

**Key decision:** In-process ChromaDB vs. SQLite `vec0` extension vs. plain NumPy cosine similarity. Recommend: start with plain NumPy (no new dependency) for <10K findings; graduate to ChromaDB when scale requires it.

### Suggestion 2: Agent-to-agent finding linking

| Component | Type | Effort |
|-----------|------|--------|
| `references: [uuid]` field in finding YAML schema | New schema field | 0.1 day |
| Router cross-reference extraction | Modify (~20 LOC) | 0.3 day |
| `references` edges in graph.json | New edge type | 0.2 day |
| Dashboard "Referenced by" / "Builds on" links | New (~50 LOC) | 0.3 day |
| Graph Explorer reference chain highlighting | New (~30 LOC) | 0.2 day |
| **Total** | | **~1-2 days** |

### Suggestion 3: Activity timeline

| Component | Type | Effort |
|-----------|------|--------|
| `<ActivityTimeline>` component (replaces `<ActivityFeed>`) | New (~200 LOC) | 1 day |
| Filter by agent, action type, project | (~50 LOC) | 0.3 day |
| "Replay" mode — animate past events on graph | New (~80 LOC) | 0.5 day |
| **Total** | | **~1-2 days** |

### Suggestion 4: Pluggable extractor pipeline

| Component | Type | Effort |
|-----------|------|--------|
| `daemon/extractors.py` — Extractor protocol + registry | New (~100 LOC) | 1 day |
| Built-in extractors: code-dependency, security, perf, ADR | New (~200 LOC) | 2 days |
| `~/.agentic-os/extractors/` user directory | New (~30 LOC) | 0.3 day |
| Router change: run extractor pipeline on findings | Modify (~30 LOC) | 0.3 day |
| Dashboard extractor status column | New (~40 LOC) | 0.3 day |
| **Total** | | **~1-2 weeks** |

### Suggestion 5: LLM-powered semantic graph embedding

| Component | Type | Effort |
|-----------|------|--------|
| `daemon/llm_extractor.py` — LLM entity extraction | New (~150 LOC) | 2 days |
| `auto_extract` flag on finding ingest | Config | 0.1 day |
| `auto_extracted` edge type with `confidence` score | New edge type | 0.3 day |
| Dashboard dashed/auto-edge styling | New (~30 LOC) | 0.3 day |
| Configurable model (Ollama/OpenAI/Claude) | New (~50 LOC) | 0.5 day |
| **Total** | | **~2-3 weeks** |

### Suggestion 6: Multi-project graph merge

| Component | Type | Effort |
|-----------|------|--------|
| `GET /api/merge?projects=noor,mailo` endpoint | New (~60 LOC) | 0.5 day |
| Dashboard "Cross-Project" view toggle | New (~50 LOC) | 0.3 day |
| Graph Explorer project-color support | New (~40 LOC) | 0.3 day |
| Cross-project edge heuristics | New (~50 LOC) | 0.5 day |
| **Total** | | **~1-2 weeks** |

---

## Existing Infrastructure Already Built (Leverage)

| Component | File | Status |
|-----------|------|--------|
| Watcher (watchdog inbox monitor) | `daemon/watcher.py` | ✅ Working |
| Router (inbox event dispatcher) | `daemon/router.py` | ✅ Working |
| Graph Engine (Graphify wrapper) | `daemon/graph_engine.py` | ✅ Working |
| Agent Registry (SQLite CRUD) | `daemon/registry.py` | ✅ Working |
| FastAPI routes + WebSocket | `daemon/api.py` | ✅ Working |
| Finding/decision ingestion | `daemon/router.py` | ✅ Working |
| WebSocket events (agent:online, graph:updated, etc.) | `daemon/api.py` | ✅ Working |
| Dashboard (project overview, detail, graph query) | `dashboard/` | ✅ Working |
| Cytoscape.js graph explorer | (designed, Phase 2) | 🔨 In plan |
| Project CRUD | (designed, Phase 1) | 🔨 In plan |
| Agent management + dispatch | (designed, Phase 3) | 🔨 In plan |

---

## Open Questions (need user input)

1. **Embedding model choice:** Sentence-transformers (local, no API key, heavier install) vs. OpenAI embeddings (API key, lighter) vs. Ollama (local, already may be installed)? **Recommend: sentence-transformers `all-MiniLM-L6-v2` for V1 — fast, local, free. Add OpenAI/Ollama as configurable backends.**

2. **LLM extractor model:** Should the semantic graph embedding (Suggestion 5) use a local model (Ollama) or an API (OpenAI/Claude)? **Recommend: configurable — default to Ollama if detected, fallback to OpenAI.**

3. **Vector store choice:** Plain NumPy cosine similarity (zero deps) vs. ChromaDB (better for >10K vectors) vs. SQLite `vec0` extension? **Recommend: plain NumPy for V1 (<10K findings); graduate to ChromaDB at scale.**

4. **Multi-project merge scope:** Should the cross-project view be read-only or allow cross-project queries? **Recommend: read-only for V1 — display merged graphs. Cross-project queries are P2.**

5. **Agent marketplace scope:** Should agents publish capabilities to each other (machine-readable) or to the human (dashboard)? **Recommend: human-facing dashboard first; machine-readable capability discovery is P2.**

6. **Git integration depth:** Should graph snapshots be automatic (every commit) or manual (user triggers)? **Recommend: automatic — watcher detects `.git/HEAD` changes. Configurable to disable.**

---

## Recommended Sequencing (2-month roadmap)

### Sprint 1 (Week 1-2): Semantic layer + visualization

- **Days 1-3:** Vector embedding search (Suggestion 1)
- **Days 4-5:** Agent-to-agent finding linking (Suggestion 2)
- **Days 6-8:** Activity timeline (Suggestion 3)
- **Days 9-10:** Integration testing + polish

**Sprint 1 outcome:** Agentic OS gains semantic search over findings, agents can cross-reference each other's work, and the dashboard has a proper activity timeline.

### Sprint 2 (Week 3-4): Extractor pipeline

- **Days 11-17:** Pluggable extractor pipeline (Suggestion 4)
- **Days 18-20:** Built-in extractors (code-dependency, security, ADR)

**Sprint 2 outcome:** Customizable ingestion pipeline. Users can write their own extractors.

### Sprint 3 (Week 5-6): LLM enrichment + cross-project

- **Days 21-28:** LLM-powered semantic graph embedding (Suggestion 5)
- **Days 29-30:** Multi-project graph merge (Suggestion 6)

**Sprint 3 outcome:** Automatic knowledge extraction from findings. Cross-project graph insights.

### Sprint 4 (Week 7-8): Backlog exploration

- Suggestions 7-10 (marketplace, session replay, metrics, git versioning) — depending on user interest

---

## Verification Checklist (when feeding into writing-plans)

- [ ] Plan respects the existing architecture: FastAPI + SQLite + Watchdog + Graphify
- [ ] Plan does NOT add new infrastructure dependencies (no Docker, no Neo4j, no external DB)
- [ ] Plan preserves the filesystem inbox protocol (no SDK requirement)
- [ ] Plan preserves single-process commitment (`agentic-os start` must remain the only command)
- [ ] Plan includes tests for each new feature (pytest for daemon, Playwright for dashboard)
- [ ] Plan respects the existing test patterns: 22 existing tests, smoke-test.sh
- [ ] Plan does NOT break the Phase 1-3 features in active development (Project CRUD, Graph Explorer, Agent Management)
- [ ] Plan includes WebSocket event additions where applicable

---

## Next Step

1. Review this file + `report.md` + `suggestions.md` with stakeholders
2. Confirm the open questions above
3. Load the `writing-plans` or `plan` skill with this file as context
4. Generate the full implementation plan
5. Re-run this competitor analysis in Q4 2026 — the agent memory category is evolving rapidly
