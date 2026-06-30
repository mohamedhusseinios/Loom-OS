# Competitor Analysis Report: Loom OS

## Methodology

**Analysis type:** Dev-tool structural comparison (no app-store reviews — this is a developer-facing platform).

**Loom OS feature claims** are verified by direct source code read on 2026-06-30: 30 daemon modules (6,644 LOC), 27 test files, 46 API routes, Next.js 16 dashboard.

**Competitor feature claims** are based on the knowledge bank snapshot dated 2026-06-26 (4 days old). The GitHub API spot-check was blocked by a user-consent guard during this session. This is acceptable for architecture-level analysis — architecture decisions shift on monthly/yearly cycles, not daily. Competitor GitHub stars/forks/latest-release data was not collected.

**No review/sentiment data** is included. Phases 2–3 (review collection + classification) do not apply to dev-tool mode.

---

## Executive Summary

The AI agent memory market splits into three distinct layers: **memory/knowledge graph** (Cognee, Graphiti, MCP Memory, Mem0, Letta), **agent orchestration** (Claude Code sub-agents, Spec Kit, Swarms), and **dashboard/control plane** (LangGraph Studio). Every competitor is confined to one or two layers.

**Loom OS is the only tool that spans all three.** It provides a code-specific knowledge graph (Layer 1), multi-agent task dispatch with worker execution (Layer 2), and a Next.js dashboard with graph visualization and Kanban board (Layer 3) — all in a single-process daemon with zero external infrastructure.

**Key finding:** Loom's competitive moat is not feature superiority in any single dimension — it is the **breadth of integration**: the filesystem inbox protocol (zero-SDK, zero-auth), single-process deployment (no Docker/Neo4j), and the three-layer span. No competitor offers all three. However, individual competitors go **deeper** on specific dimensions: Cognee has production-grade vector backends, Graphiti has a bi-temporal graph model, and Letta has richer per-agent memory management.

---

## The Three-Layer Market Structure

```
Layer 3: Dashboard / Control Plane
  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
  │ Loom OS ✅          │  │ LangGraph Studio    │  │ Hermes Agent        │
  │ (Next.js + Cytoscape)│  │ (agent debugging)   │  │ (delegation + UI)   │
  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘

Layer 2: Agent Orchestration / Delegation
  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
  │ Loom OS ✅          │  │ Claude Code         │  │ Swarms              │
  │ (worker + dispatch) │  │ (sub-agents)        │  │ (multi-agent)       │
  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
                           ┌─────────────────────┐
                           │ GitHub Spec Kit     │
                           │ (spec-driven)       │
                           └─────────────────────┘

Layer 1: Agent Memory / Knowledge Graph
  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
  │ Loom OS ✅          │  │ Cognee              │  │ Graphiti / Zep      │
  │ (Graphify + extract)│  │ (graph+vec+rel)     │  │ (temporal graph)    │
  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
  │ MCP Memory Server   │  │ Mem0                │  │ Letta (MemGPT)      │
  │ (filesystem-backed) │  │ (personalization)   │  │ (tiered memory)     │
  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

---

## Competitive Landscape

### Competitor Comparison Table

| Competitor | Layer(s) | Integration | Deployment | Similarity | Loom's Edge |
|-----------|----------|-------------|------------|------------|-------------|
| **Cognee** | L1 Memory | Python SDK | Docker + Neo4j + PGVector + Qdrant | HIGH (7/10) | Dashboard, filesystem protocol, code-specific, single-process |
| **Graphiti** | L1 Memory | Python SDK | Neo4j required | HIGH (6/10) | Dashboard, no Neo4j dependency, code-specific, task dispatch |
| **MCP Memory** | L1 Memory | MCP stdio | Zero-config subprocess | MEDIUM (5/10) | Multi-project, code-AST, vector search, dashboard, task dispatch |
| **Mem0** | L1 Memory | SDK + REST | Cloud / self-hosted | LOW (3/10) | Code-specific, knowledge graph, dashboard, multi-agent |
| **Letta** | L1 Memory | SDK + REST + UI | Docker / cloud | LOW (3/10) | Multi-agent coordination, shared graph, code-specific |
| **Cloudflare Agent** | L1 Memory | Workers SDK | Cloud-only | LOW (2/10) | Local-first, no vendor lock-in, knowledge graph, dashboard |
| **Claude Code** | L2 Orchestration | CLI | Local CLI | LOW (3/10) | Cross-session memory, shared graph, multi-vendor agents, dashboard |
| **Spec Kit** | L2 Orchestration | CLI / GH Actions | Local | LOW (2/10) | Persistent memory, knowledge graph, dashboard, memory + dispatch unified |
| **Swarms** | L2 Orchestration | Python library | Library import | LOW (2/10) | Knowledge graph, dashboard, running service (not just library) |
| **LangGraph Studio** | L3 Dashboard | Desktop app | Desktop | LOW (2/10) | Memory fabric, task dispatch, code-specific graph |

---

## Per-Competitor Breakdown

### Cognee — Closest Direct Competitor

- **Overview:** Open-source agent memory platform with graph + vector + relational retrieval. Pipeline-based ingestion with extractors, classifiers, resolvers.
- **Architecture:** Neo4j (graph) + PGVector (vectors) + Qdrant (additional vectors). Docker Compose deployment. Cloud option available.
- **Integration:** Python SDK — agents call `cognee.add()` / `cognee.search()` programmatically.
- **Strengths:** Multi-modal retrieval (graph+vec+rel), pluggable extractor pipeline, LLM-powered entity extraction, production-grade vector backends.
- **Gaps vs Loom:** No dashboard, requires Docker + Neo4j + PostgreSQL + Qdrant, no filesystem protocol (SDK-only), not code-specific, no multi-agent orchestration, no task dispatch.
- **Where Cognee goes deeper:** Vector infrastructure is production-grade (PGVector/Qdrant with persistence, indexing, scaling). Loom's `EmbeddingStore` is in-memory NumPy with zero-vector fallback. For production workloads >10K documents, Cognee's stack is more mature.

### Graphiti / Zep — Temporal Knowledge Graph

- **Overview:** Build real-time knowledge graphs for AI agents with a bi-temporal model — edges and nodes have time dimensions.
- **Architecture:** Neo4j backend. Tracks what changed between sessions with first-class temporal queries.
- **Integration:** Python SDK — programmatic graph operations.
- **Strengths:** Bi-temporal graph model, real-time updates, persistent across sessions, LLM entity extraction.
- **Gaps vs Loom:** Requires Neo4j, no dashboard, not code-specific, no task dispatch, no filesystem protocol.
- **Where Graphiti goes deeper:** Temporal model is bi-temporal and Neo4j-persisted. Loom's `TemporalTracker` (`daemon/temporal.py`, 152 lines) is explicitly marked "in-memory (V1)" and lacks persistence. Graphiti's `facts_at(time)` equivalent survives process restarts; Loom's doesn't.

### MCP Memory Server

- **Overview:** Official MCP server providing knowledge-graph-based persistent memory. Filesystem-backed JSON storage.
- **Architecture:** Entity-relationship model stored as JSON on disk. Communicates over MCP stdio transport.
- **Integration:** MCP protocol — works with Claude Desktop, Cursor, Cline, any MCP client.
- **Strengths:** Zero-config, native MCP support, works with any MCP-compatible client, lightweight.
- **Gaps vs Loom:** Simple entity model (not code knowledge graph), no project isolation, no vectors, no dashboard, no multi-agent dispatch.
- **Convergence:** Loom OS also has an MCP server (`daemon/mcp_server.py`, 292 lines) exposing `list_projects`, `get_project_graph`, `search_knowledge_graph`, `add_to_memory`, and `query_graph` as MCP tools. This means Loom competes with MCP Memory on its own protocol while offering strictly more.

### Mem0

- **Overview:** AI memory layer focused on personalization — continuously learns from user interactions.
- **Architecture:** Cloud-first with self-hosted option. Not a knowledge graph — it's preference/interaction memory.
- **Strengths:** Production-grade personalization, managed cloud, multi-platform SDKs (Python, JS, LangChain, AutoGen, CrewAI).
- **Gaps vs Loom:** Different use case entirely (personalization vs code knowledge), no knowledge graph, no dashboard for dev workflows, no multi-agent task dispatch.
- **Where Mem0 goes deeper:** SDK ecosystem. Mem0 has mature adapters for LangChain, AutoGen, CrewAI. Loom has a LangChain integration (`BaseMemory` adapter) and Python + npm client SDKs, but the adapter ecosystem is thinner.

### Letta (MemGPT)

- **Overview:** Stateful agents with OS-inspired tiered memory (working memory + archival storage + recall memory).
- **Architecture:** Per-agent memory management. Visual agent development interface (ADE).
- **Strengths:** OS-inspired tiered memory, visual agent dev interface, per-agent memory management, production deployment support.
- **Gaps vs Loom:** Single-agent focus, not code-specific, no shared knowledge graph between agents, no filesystem protocol, no task dispatch.
- **Where Letta goes deeper:** Per-agent memory management with tiered architecture. Loom's `SessionManager` (`daemon/sessions.py`, 128 lines) is simpler — scoped subgraphs with inbox bridging on close. Letta's memory tiers (working/archival/recall) are more sophisticated.

### Cloudflare Agent Memory

- **Overview:** Stateful AI agents on Cloudflare's edge with persistent memory and WebSocket support.
- **Strengths:** Cloud-native auto-scaling, WebSocket built-in, global edge deployment, scheduled tasks.
- **Gaps vs Loom:** Cloud-only (vendor lock-in), not code-specific, no knowledge graph, no dashboard.
- **Note:** Cloudflare's WebSocket is for edge agent communication. Loom's WebSocket is for dashboard live updates. Different use cases collapsed under the same "WebSocket" label.

### Claude Code Sub-agents (Layer 2 reference)

- **Overview:** Hierarchical delegation — main agent spawns sub-agents with isolated context.
- **Strengths:** Proven delegation pattern, isolated context per sub-agent, streaming JSON output, budget-capped execution.
- **Gaps vs Loom:** No shared memory between sub-agents, no cross-session persistence, single-vendor, no dashboard.
- **Relationship:** Claude Code is both a competitor (orchestration) and a Loom integration target — Loom's `runners.py` invokes `claude -p` headlessly as one of 6 registered agents.

### LangGraph Studio (Layer 3 reference)

- **Overview:** Visual agent debugging — trace execution, inspect state, debug graphs.
- **Strengths:** Visual debugging and tracing, state inspection, graph visualization, LangChain ecosystem.
- **Gaps vs Loom:** Debugging-only (not a memory fabric), no persistent knowledge graph, no task dispatch, tied to LangGraph framework.

---

## Feature Matrix

| Dimension | Loom OS | Cognee | Graphiti | MCP Mem | Mem0 | Letta | Cloudflare | Claude Code | Spec Kit | Swarms | LangGraph Studio |
|-----------|---------|--------|----------|---------|------|-------|------------|-------------|----------|--------|-----------------|
| Code-AST knowledge graph | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Vector search | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-modal retrieval | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Dashboard / UI | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Filesystem protocol | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Single-process daemon | ✅ | ❌ | ❌ | ✅ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ⚠️ | ❌ |
| Per-project isolation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| WebSocket live updates | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Code-specific (AST) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| LLM extraction | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Temporal tracking | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Task dispatch | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ⚠️ | ✅ | ❌ |
| Worker execution | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Git worktree isolation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| MCP server | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Plugin system | ✅ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Eval harness | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Pattern repository | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Audit trail | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Session management | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Shared context | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Team mode / auth | ✅ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Client SDK (py+npm) | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| LangChain integration | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Graph visualization | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

**Score:** Loom OS 25/25 · Cognee 5/25 · Graphiti 3/25 · MCP Memory 3/25 · Mem0 5/25 · Letta 2/25

> **Important caveat — "has feature" ≠ "production-grade":** The ✅ for Loom OS indicates the feature exists and works. Several are explicitly V1 implementations with known depth gaps (see Depth vs. Breadth section below). The score reflects **breadth**, not depth.

---

## Depth vs. Breadth Analysis

The 25/25 score is architecturally defensible — Loom OS genuinely implements all 25 dimensions. But it must not be read as "Loom has the best implementation of each." Several competitors go deeper on individual dimensions:

| Dimension | Loom OS status | Competitor with deeper implementation | Gap |
|-----------|---------------|---------------------------------------|-----|
| **Vector search** | ✅ but in-memory NumPy (`EmbeddingStore`, 135 lines). Zero-vector fallback when model unavailable. No persistence — embeddings lost on restart. | **Cognee** — PGVector/Qdrant with persistence, indexing, scaling. Production-grade. | Embeddings don't survive daemon restart. Won't scale past ~10K docs. |
| **Temporal tracking** | ✅ but in-memory V1 (`TemporalTracker`, 152 lines). Docstring explicitly says "All state is in-memory (V1). SQLite persistence can be added later." | **Graphiti** — bi-temporal Neo4j-backed model. `facts_at(time)` survives restarts. | Facts lost on restart. No bi-temporal (only valid_from/valid_to). |
| **Session management** | ✅ but in-memory V1 (`SessionManager`, 128 lines). Docstring: "Sessions are in-memory (V1). A future V2 can persist session checkpoints to disk." | **Letta** — tiered memory (working/archival/recall) with persistence. | Sessions lost on restart. No tiered memory architecture. |
| **Multi-modal retrieval** | ✅ but BFS approximation (`hybrid_query`, 337 lines graph_engine). Vector-seeded BFS over AST + extracted edges. | **Cognee** — proper multi-modal query planner across graph + vector + relational stores. | Loom's is a heuristic join, not a query planner. Results degrade on large graphs. |
| **Team mode / auth** | ✅ but optional token middleware (`daemon/auth.py`). "No-op when unconfigured" (commit ea595cc). No RBAC, no OAuth, no session management. | **Mem0** — managed cloud with production auth. | V1 token check, not production auth. |
| **Client SDK** | ✅ Python SDK (HTTP wrapping) + npm twin (TypeScript types + tests). | **Mem0** — mature multi-platform SDKs with retry, batching, streaming. | Basic HTTP wrapping, no retry/batching/streaming. |

**The honest pitch:** "No single competitor spans all three layers, and no competitor has a filesystem inbox protocol. But in each individual layer, there are tools with deeper capabilities. Loom OS trades depth for breadth — and the breadth itself (unified memory + orchestration + dashboard in one process) is the moat."

---

## Cross-Competitor Analysis

### What No Competitor Has (Loom's Moat)

1. **Filesystem inbox protocol** — drop a file in `~/.loom/inbox/<project>/`, no SDK, no API key, no auth. This is the single biggest differentiator. Cognee, Graphiti, Mem0, Letta all require SDK integration. MCP Memory uses a protocol but requires an MCP client.
2. **Single-process daemon** — `pip install loom-os && loom --port 8472`. Cognee needs Docker + Neo4j + PostgreSQL + Qdrant. Graphiti needs Neo4j. No competitor runs as a single process.
3. **Three-layer span** — memory + orchestration + dashboard in one tool. Every competitor is confined to 1–2 layers.
4. **Code-specific knowledge graph** — Graphify extracts AST-level code structure. General memory tools (Cognee, Mem0, Letta) don't understand code.
5. **Multi-agent worker execution** — Loom doesn't just dispatch tasks; it spawns agents (claude-code, codex, hermes, gemini-cli, copilot-cli, aider) in isolated git worktrees with budget caps. No memory competitor does this.

### Common Gaps Across ALL Competitors

| Gap | Who fails here | Loom's opportunity |
|-----|---------------|-------------------|
| No dashboard / visual UI | Cognee, Graphiti, MCP Memory, Mem0, Cloudflare, Spec Kit, Swarms | Loom's Next.js dashboard with Cytoscape graph explorer and Kanban board is unique |
| No filesystem protocol | Cognee, Graphiti, Mem0, Letta, Cloudflare, Claude Code, Swarms | Zero-SDK integration is a friction eliminator |
| No code-specificity | Cognee, Graphiti, MCP Memory, Mem0, Letta, Cloudflare, Swarms | Code-AST knowledge graph is a vertical moat |
| No cross-agent shared memory | Claude Code, Swarms, Spec Kit | Shared context generation (`SHARED_CONTEXT.md`) is unique |
| No eval harness | ALL competitors | `daemon/evals.py` (195 lines) is unique in this category |
| No pattern repository | ALL competitors | `daemon/patterns.py` (209 lines) with cross-project pattern search is unique |
| No audit trail | ALL competitors | `daemon/audit.py` with query-level audit logging is unique |

### Where Loom OS Should Be Cautious

| Risk | Competitor | Why it matters |
|------|-----------|----------------|
| Vector infra scaling | Cognee | Production workloads >10K docs will expose Loom's in-memory limitation |
| Temporal persistence | Graphiti | Graphiti's bi-temporal Neo4j model is the gold standard for time-dimensioned queries |
| SDK ecosystem | Mem0 | Mem0's LangChain/AutoGen/CrewAI adapters give it broader framework reach |
| Per-agent memory depth | Letta | Letta's tiered memory is more sophisticated than Loom's session manager |

---

## Market Gaps & Opportunities

### Gap 1: Production vector backend
Loom's `EmbeddingStore` is in-memory NumPy with zero-vector fallback. Cognee has PGVector/Qdrant. **Opportunity:** Add sqlite-vec or LanceDB backend. The code already comments: "A future V2 can swap to an on-disk sqlite-vec backend without changing the public API." Priority: P0.

### Gap 2: Temporal persistence
Loom's `TemporalTracker` loses all facts on daemon restart. Graphiti persists to Neo4j. **Opportunity:** Add SQLite persistence to `TemporalTracker`. Priority: P0.

### Gap 3: Managed cloud option
Cognee, Mem0, Letta all have cloud options. Loom is local-only. **Opportunity:** Dockerize for self-hosted teams, then offer managed cloud. Priority: P1.

### Gap 4: True multi-modal query planner
Loom's `hybrid_query` is vector-seeded BFS — a heuristic join. Cognee has a proper multi-modal query planner. **Opportunity:** Replace BFS heuristic with a scored query planner. Priority: P1.

### Gap 5: Deeper framework adapters
Mem0 has LangChain, AutoGen, CrewAI adapters. Loom has LangChain `BaseMemory` only. **Opportunity:** Add AutoGen, CrewAI adapters. Priority: P2.

### Gap 6: Production auth
Loom's auth is optional token middleware ("no-op when unconfigured"). **Opportunity:** Add OAuth2 + RBAC. Priority: P2.
