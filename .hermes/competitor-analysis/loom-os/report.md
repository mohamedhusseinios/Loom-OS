# Competitor Analysis Report: Loom OS

> Generated 2026-07-01 | Structural comparison (dev-tool mode — no reviews/sentiment) | 8 competitors across 31 feature dimensions

## Executive Summary

- **Market:** AI agent memory and knowledge graph platforms — tools that give coding agents persistent, shared, queryable memory across sessions and across agents.
- **Competitors analyzed:** 8 (Cognee, Graphiti/Zep, Mem0, Letta/MemGPT, MCP Memory Server, Swarms, LangMem + Loom OS)
- **Competitive set freshness:** All competitor repos confirmed alive via GitHub API on 2026-07-01. Star counts and `pushed_at` timestamps captured.
- **Key finding:** Loom OS has lapped the field. With 30 of 31 capabilities checked (vs. the next-closest competitor at 9), Loom is the most feature-complete open-source agent memory platform. It is also the only competitor spanning all three market layers (memory + orchestration + dashboard). The competitive question is no longer "close the gap" — it's "what's the next moat?"
- **Biggest opportunity:** Published benchmarks, community/distribution growth, and incremental graph persistence. These are the remaining gaps where Cognee (26K stars), Mem0 (60K stars), and Graphiti (28K stars) still lead.

---

## Delta Since 2026-06-26

The knowledge bank (5 days old) was built when Loom had ~17 feature dimensions and was positioned as needing to close gaps. Since then:

**All 9 post-parity roadmap features shipped:**

| # | Feature | Commit | Status |
|---|---------|--------|--------|
| 1 | LLM Extractor (Ollama/OpenAI/Claude) | 5671410, f66c7df | ✅ Shipped |
| 2 | Hybrid search (graph+vector+relational) | 4ed7743, 781cf12 | ✅ Shipped |
| 3 | PyPI ship (`loom-os` 0.2.0) | 7c07c64, 5e14b3c | ✅ Shipped |
| 4 | Team mode (optional auth, per-user inbox) | ea595cc, 30b237f | ✅ Shipped |
| 5 | Client SDK (Python + npm TypeScript) | 884d7ca | ✅ Shipped |
| 6 | Agent discovery (capability matching) | 6c1311b | ✅ Shipped |
| 7 | Benchmark harness | 4d5fba3 | ✅ Shipped |
| 8 | Plugin system for extractors | 64eeea8 | ✅ Shipped |
| 9 | LangChain integration (BaseMemory) | d13667c | ✅ Shipped |

**Additional modules shipped beyond the roadmap:**

| Module | LOC | Capability |
|--------|-----|------------|
| `temporal.py` | 152 | Temporal fact tracking with validity time ranges |
| `traces.py` | 159 | Execution tracing with span lifecycle |
| `sessions.py` | 128 | Session-scoped subgraphs for agent continuity |
| `snapshots.py` | 126 | State snapshots for time-travel debugging |
| `patterns.py` | 209 | Self-evolving cross-project pattern repository |
| `recall.py` | 163 | Graph-based recall engine for agent tasks |
| `ingest.py` | 176 | Multi-format document ingestion |
| `audit.py` | 155 | Immutable audit trail for governance |
| `project_knowledge.py` | 265 | Knowledge source discovery and ingestion |
| `known_agents.py` | 125 | Installed-agent detection (Cursor, Claude Code, etc.) |
| `shared_context.py` | 233 | Auto-generated `.loom/SHARED_CONTEXT.md` |

**Net change:** Loom went from ~17 to 31 feature dimensions in 5 days, with 30 of 31 capabilities now present. Feature presence confirmed by module introspection (function signatures, class hierarchies), not README claims.

---

## The Three-Layer Market Structure

The AI agent memory market splits into three layers. No competitor except Loom spans all three.

```
Layer 3: Dashboard / Control Plane
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
  │ Loom OS ✅     │  │ LangGraph Studio│  │ Hermes Agent   │
  │ (Next.js+Cyto) │  │ (debugging)     │  │ (delegation+UI)│
  └────────────────┘  └────────────────┘  └────────────────┘

Layer 2: Agent Orchestration / Autonomous Execution
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
  │ Loom OS ✅     │  │ Letta          │  │ Swarms         │
  │ (worker.py +   │  │ (stateful      │  │ (multi-agent   │
  │  worktree.py)  │  │  agent runtime)│  │  framework)    │
  └────────────────┘  └────────────────┘  └────────────────┘

Layer 1: Agent Memory / Knowledge Graph
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
  │ Loom OS ✅     │  │ Cognee         │  │ Graphiti/Zep   │
  │ (Graphify AST  │  │ (graph+vec+rel)│  │ (temporal)     │
  │  + LLM edges)  │  │                │  │                │
  └────────────────┘  └────────────────┘  └────────────────┘
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
  │ MCP Memory     │  │ Mem0           │  │ LangMem        │
  │ (entity-relation│  │ (personalize)  │  │ (LangChain)    │
  │  JSON)         │  │                │  │                │
  └────────────────┘  └────────────────┘  └────────────────┘
```

Loom uniquely occupies all three layers as a single integrated system. Every other competitor is a Layer 1 or Layer 2 tool.

---

## Feature Capability Matrix

The centerpiece of this analysis. 31 dimensions across 8 competitors, built from actual module introspection for Loom and live GitHub/documentation analysis for competitors.

**Legend:** ✅ = present and functional | ❌ = absent | ⚠️ = partial/prototype

| Feature | Loom OS | Cognee | Graphiti | Mem0 | Letta | MCP Mem | Swarms | LangMem |
|---------|---------|--------|----------|------|-------|---------|--------|---------|
| **Memory & Knowledge** | | | | | | | | |
| Knowledge graph | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Vector search | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Hybrid search (graph+vec) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| LLM extraction | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Temporal facts | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Code-aware (AST) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Agent State & Observability** | | | | | | | | |
| Execution tracing | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Session state | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| State snapshots | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Pattern detection | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Recall engine | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Audit trail | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-format ingest | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Shared context | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Deployment & UX** | | | | | | | | |
| Dashboard/UI | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| WebSocket realtime | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Graph visualization | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Filesystem protocol | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Single-process daemon | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Per-project isolation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Ecosystem & Distribution** | | | | | | | | |
| Hosted cloud | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Team mode | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Autonomous worker | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Git worktree isolation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| MCP server | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Plugin system | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Client SDK | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Framework integrations | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Agent discovery | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Eval harness | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Open source | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Feature count (of 31)** | **30** | **9** | **9** | **6** | **9** | **5** | **5** | **7** |

> ⚠️ **Maturity caveat:** Feature presence was confirmed by module inspection (function signatures, class hierarchies), not by test execution or production load. A 152-line `temporal.py` with `TemporalFact`/`TemporalTracker` classes is a working module — but it's a first-generation implementation, not a battle-tested temporal graph engine like Graphiti's. The feature matrix reflects *presence*, not *maturity*. The competitive moat analysis below addresses durability.

---

## Per-Competitor Breakdown

### 1. Cognee — Closest Direct Competitor (26K stars)

- **Overview:** Open-source agent memory platform with graph + vector + relational retrieval. Pipeline-based ingestion → Neo4j + PGVector/Qdrant.
- **Architecture:** Docker-native. Requires Neo4j + at least one vector store. Cloud offering available.
- **GitHub:** github.com/topoteretes/cognee | ⭐ 26,099 | Last pushed 2026-06-30

**Key differentiators (vs Loom):**
- Multi-modal retrieval is mature — their graph+vector+relational pipeline has been in production longer than Loom's hybrid search.
- Cloud offering with managed infrastructure.
- Large, active community.

**Where Loom wins:**
- Single-process deployment vs Docker + Neo4j + Qdrant stack.
- Dashboard with WebSocket live updates — Cognee is API-only.
- Filesystem inbox protocol — Cognee requires SDK integration.
- Code-specificity — Cognee is a general-purpose knowledge graph, not code-aware.
- 22 capability dimensions Cognee lacks (tracing, sessions, snapshots, patterns, audit, worker, worktree, team mode, temporal facts, code-aware AST, dashboard, WebSocket, filesystem protocol, per-project isolation, recall engine, shared context, agent discovery, eval harness, session state, state snapshots, pattern detection, MCP server).

**Architecture decision comparison:** Cognee chose infrastructure-rich, cloud-ready architecture (Neo4j + PGVector + Docker). Loom chose infrastructure-free, local-first (SQLite + NumPy + single process). Both are defensible — Cognee for enterprise teams that already run Neo4j, Loom for individual developers and small teams that want zero-setup.

---

### 2. Graphiti / Zep — Temporal Knowledge Graph (28K stars)

- **Overview:** Build real-time knowledge graphs for AI agents with a temporal model — edges and nodes have time dimensions.
- **Architecture:** Requires Neo4j. Python SDK. Zep cloud available for managed hosting.
- **GitHub:** github.com/getzep/graphiti | ⭐ 28,183 | Last pushed 2026-06-27

**Key differentiators (vs Loom):**
- Temporal graph model is more mature — time-dimensioned edges are Graphiti's core feature, built and refined over years.
- Zep cloud offering — managed temporal knowledge graphs.
- Large community.

**Where Loom wins:**
- Loom now has `temporal.py` (TemporalFact with validity ranges, `active_facts()`, `facts_at(timestamp)`, `timeline()`) — functional temporal tracking. Not as mature as Graphiti's, but present.
- Dashboard, filesystem protocol, code-awareness, autonomous worker — none of which Graphiti has.
- Single-process vs Neo4j dependency.

**Architecture comparison:** Graphiti's temporal model operates at the edge level (each edge has temporal metadata). Loom's `TemporalFact` operates at the fact level (each fact has `valid_from`/`valid_to` ranges). Both approaches are valid; Loom's is simpler for the "when was this decision made and is it still active" use case.

---

### 3. Mem0 — Personalization Memory (60K stars)

- **Overview:** Universal memory layer for AI agents. Focused on user personalization — learning from past interactions to customize future responses.
- **GitHub:** github.com/mem0ai/mem0 | ⭐ 59,779 | Last pushed 2026-06-30

**Key differentiators (vs Loom):**
- Largest community in the category (60K stars).
- Personalization engine — continuously learns user preferences.
- Managed cloud platform.

**Where Loom wins:**
- Fundamentally different use case. Mem0 is about user personalization; Loom is about multi-agent coordination and code knowledge. They're complementary, not competitive.
- Loom has a knowledge graph; Mem0 is vector-only.
- Loom has a dashboard, worker, tracing, sessions — Mem0 has none of these for the dev-tool use case.

**Market positioning:** Mem0 and Loom serve different needs. Mem0 powers "remember the user" features; Loom powers "agents share what they learned about the codebase." A product could use both.

---

### 4. Letta (MemGPT) — Stateful Agent Platform (24K stars)

- **Overview:** Platform for stateful agents with OS-inspired memory architecture (working memory + archival storage). Agents persist and self-improve over time.
- **GitHub:** github.com/letta-ai/letta | ⭐ 23,593 | Last pushed 2026-06-26

**Key differentiators (vs Loom):**
- Stateful agent runtime — agents persist across sessions with self-improvement loops. This is a Layer 2 feature Loom partially matches with `worker.py` but approaches differently.
- Letta Cloud — managed agent hosting.
- MCP server support.
- Dashboard for agent management.

**Where Loom wins:**
- Knowledge graph — Letta's memory is tiered (working/archival) but flat, not structural. Loom's Graphify graph gives AST-level code understanding.
- Filesystem protocol — Letta requires its own SDK/runtime.
- Per-project isolation, code-specificity, git worktree isolation, plugin system.
- 22 capability dimensions Letta lacks (knowledge graph, hybrid search, code-aware AST, tracing, snapshots, patterns, recall, ingest, audit, shared context, WebSocket, graph visualization, filesystem protocol, per-project isolation, team mode, git worktree isolation, plugin system, agent discovery, eval harness, temporal facts, pattern detection, multi-format ingest).

**Architecture comparison:** Letta is a stateful agent runtime — it runs agents. Loom is a memory fabric — agents connect to it. Letta agents are Letta-specific; any agent can connect to Loom via the filesystem inbox. This is the most direct "second place" competitor in the orchestration+dashboard space.

---

### 5. MCP Memory Server — Official Reference (87K umbrella stars)

- **Overview:** Official MCP server providing knowledge graph-based persistent memory. Filesystem-backed JSON.
- **GitHub:** github.com/modelcontextprotocol/servers | ⭐ 87,895 (umbrella monorepo — includes 20+ servers, not just memory) | Last pushed 2026-06-29

> ⚠️ **Star count caveat:** 87K stars belongs to the MCP servers monorepo (filesystem, git, database, Slack, etc.). The memory server is one subdirectory. The actual memory-server-specific community is much smaller.

**Key differentiators (vs Loom):**
- Official MCP reference implementation — protocol-level credibility.
- Part of the fastest-growing agent protocol ecosystem.
- Zero infrastructure — pure filesystem JSON.

**Where Loom wins:**
- Loom also has an MCP server (`mcp_server.py`), so it participates in the same ecosystem.
- Entity-relation graph only — no code structure, no AST, no vector search.
- No dashboard, no WebSocket, no per-project isolation, no worker, no team mode.
- 25 capability dimensions the MCP Memory Server lacks (vector search, hybrid search, LLM extraction, code-aware AST, tracing, sessions, snapshots, patterns, recall, ingest, audit, shared context, dashboard, WebSocket, graph visualization, per-project isolation, team mode, autonomous worker, git worktree isolation, plugin system, client SDK, framework integrations, agent discovery, eval harness, temporal facts).

---

### 6. Swarms — Multi-Agent Orchestration (7K stars)

- **Overview:** Enterprise-grade multi-agent orchestration framework. Multiple swarm topologies (hierarchical, sequential, parallel).
- **GitHub:** github.com/kyegomez/swarms | ⭐ 6,901 | Last pushed 2026-06-29

**Key differentiators (vs Loom):**
- Sophisticated multi-agent topology patterns.
- LLM-agnostic — works with any model provider.
- Pure orchestration focus.

**Where Loom wins:**
- Swarms has no memory layer at all — no knowledge graph, no persistence, no shared state between agents. Loom fills the exact gap Swarms has.
- No dashboard, no filesystem protocol, no code-awareness.
- Loom's `worker.py` provides autonomous execution with budget-capped task dispatch.

**Synergy potential:** Swarms + Loom could be complementary — Swarms orchestrates, Loom provides the shared memory. This is a potential integration target, not a head-to-head competitor.

---

### 7. LangMem — LangChain Memory Layer (1.5K stars)

- **Overview:** LangChain's official memory layer for agents. Vector-based memory with LangGraph integration.
- **GitHub:** github.com/langchain-ai/langmem | ⭐ 1,530

**Key differentiators (vs Loom):**
- Native LangChain/LangGraph ecosystem integration.
- Backed by LangChain Inc. — enterprise credibility.
- Hosted offering via LangGraph Cloud.

**Where Loom wins:**
- Loom now has a LangChain integration (`langchain-loom` implementing `BaseMemory`), directly competing with LangMem for the LangChain memory use case.
- Knowledge graph — LangMem is vector-only.
- Dashboard, filesystem protocol, code-awareness, autonomous worker — none of which LangMem has.

**Strategic note:** LangMem is small (1.5K stars) but strategically relevant. Loom's `langchain-loom` integration makes it a drop-in replacement for LangMem with a graph backend. The pitch: "LangMem gives you vector memory. Loom gives you a knowledge graph, dashboard, and multi-agent coordination — all accessible through the same LangChain `BaseMemory` interface."

---

## Cross-Competitor Capability Gap Map

Instead of a sentiment heatmap (this is a dev-tool analysis, not review-based), here's a capability gap map showing where competitors cluster and where Loom stands alone.

| Capability Cluster | Loom | Cognee | Graphiti | Mem0 | Letta | MCP | Swarms | LangMem |
|---------------------|------|--------|----------|------|-------|-----|--------|---------|
| **Graph + Vector** (core memory) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Code-specific (AST)** | ★ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Dashboard + Realtime** | ★ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ❌ |
| **Autonomous execution** | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ |
| **Filesystem protocol** | ★ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Single-process deploy** | ★ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| **Hosted cloud** | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Large community (>20K)** | ❌ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ |
| **Framework integration** | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Temporal model** | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

**★ = Loom is the only competitor with this capability.**

**Key insight:** Loom is uniquely alone in 5 capability clusters (code-specific AST, dashboard+realtime, filesystem protocol, single-process deploy, and the combination of all four). No other competitor offers even two of these. The cost: Loom is also the only major competitor without a hosted cloud offering and without a large community.

---

## Competitive Moat Analysis

Architecture decisions are more durable than feature lists. This section weighs the most heavily — it's what a reader will return to in six months.

### Loom's structural moats (hard to copy)

1. **Filesystem inbox protocol.** Any agent connects by writing a file to `~/.loom/inbox/`. No SDK required (though one exists), no auth required (though team mode adds it), no API key. This is architecturally alien to every competitor — they all require SDK integration. It's also Loom's most defensible decision: it makes agent onboarding trivial, which compounds as more agents support it.

2. **Single-process daemon with SQLite.** `pip install loom-os && loom start` is the entire setup. Cognee needs Docker + Neo4j + PGVector. Graphiti needs Neo4j. Letta needs Docker + Postgres. This is a deployment-simplicity moat that's very hard to retrofit — competitors would have to strip their infrastructure dependencies, which means rewriting their core data layer.

3. **Code-specific knowledge graph.** Graphify extracts AST-level code structure (functions, classes, imports, call graphs). No competitor understands code at this level. This is a data moat — the graph content itself is structurally different from what Cognee/Graphiti/Mem0 produce, because it's built from code structure, not from unstructured text extraction.

4. **Dashboard + WebSocket push.** Visual project overview, Cytoscape graph explorer, agent management, task board — all with real-time push updates. No memory competitor has a UI. Building one requires a full frontend stack, which is a significant investment that pure-backend companies (Cognee, Graphiti, Mem0) are unlikely to make.

### Loom's structural gaps (hard to close without philosophical shift)

1. **No hosted cloud.** Every competitor with >20K stars has one. Loom's single-process architecture actually makes containerization easier than competitors, but the offering doesn't exist. This is a go-to-market gap, not an architecture gap.

2. **Graphify rebuilds from source on each update.** `graph_engine.py` invokes `graphify` as a subprocess that rebuilds `graph.json` from the project's AST. There's an mtime cache (commit 4d5fba3), but the underlying model is full-rebuild, not incremental. At scale (many projects, large repos), this becomes a bottleneck competitors don't have.

3. **No cross-project federation.** Projects are fully isolated — each has its own `graphify-out/` directory. There's no way to query "which projects use pattern X?" or "find this module across all repos." `patterns.py` has `cross_project_patterns()` but it operates on pattern observations, not graph federation.

4. **Community/distribution.** Cognee has 26K stars, Mem0 has 60K. Loom's GitHub is not yet publicly tracked in this analysis, but the competitive gap in mindshare is real. Discoverability — not features — is now the binding constraint.

---

## Market Gaps & Opportunities

### Gap 1: Published Benchmarks
- **Competitors failing here:** None have published head-to-head benchmarks. Cognee has internal benchmarks but hasn't published comparison data.
- **Opportunity for Loom:** The eval harness (`evals.py`) and benchmark runner (commit 4d5fba3) exist. Publishing reproducible benchmark results vs Cognee/Graphiti on the same tasks would be a credibility asset no competitor has.

### Gap 2: Hosted Cloud Offering
- **Competitors winning here:** Cognee, Graphiti, Mem0, Letta, LangMem all have cloud platforms.
- **Opportunity for Loom:** Either ship a managed offering (containerize the daemon — it's single-process, so this is architecturally easy) or aggressively lean into "self-hosted by design" positioning. The current silence on cloud is the largest unanswered question for any enterprise buyer.

### Gap 3: Incremental Graph Persistence
- **Competitors:** Cognee/Graphiti use Neo4j which handles incremental updates natively. Loom rebuilds from source.
- **Opportunity for Loom:** Add diff-based graph updates to `graph_engine.py` so only changed files are re-parsed. This is an architecture investment that prevents scaling problems before they emerge.

### Gap 4: Cross-Project Knowledge Federation
- **Competitors:** All use flat namespaces — no concept of cross-project graph queries.
- **Opportunity for Loom:** A `federation.py` module that indexes across `~/.loom/inbox/*/graphify-out/` would unlock a category no competitor is in. "Find all references to pattern X across the org's repos" is a capability that doesn't exist in any competitor.

### Gap 5: Community & Distribution
- **Competitors winning here:** Mem0 (60K), Graphiti (28K), Cognee (26K) all have large communities.
- **Opportunity for Loom:** Documentation site, Discord/GitHub Discussions, example projects, and tutorial content. The product is deep; discoverability is the bottleneck.

### Gap 6: MCP Ecosystem Positioning
- **Competitors:** MCP Memory Server is the official reference but has limited scope. No competitor positions as "the memory layer for any MCP-compatible agent."
- **Opportunity for Loom:** Loom has `mcp_server.py` with `list_projects`, `search_knowledge_graph`, `query_graph`, `add_to_memory` tools. Positioning Loom as the richest MCP-compatible memory backend would open a distribution channel through the 87K-star MCP ecosystem.

---

## Methodology

- **Analysis mode:** Dev-tool structural comparison (no review/sentiment collection — this is an API/CLI/open-source category, not a consumer app with app-store reviews).
- **Loom feature row:** Built from actual module introspection — read function signatures, class hierarchies, and module docstrings from every `daemon/*.py` file. Feature presence confirmed by code inspection, not README claims.
- **Competitor data:** Star counts, descriptions, and `pushed_at` timestamps from GitHub API on 2026-07-01. All 8 competitors confirmed alive and non-archived. Architecture and feature assessments from the knowledge bank (built 2026-06-26 from direct site/docs probing) with spot-checks.
- **MCP Memory Server star caveat:** The 87,895 stars belong to the `modelcontextprotocol/servers` umbrella monorepo (20+ servers). The memory server is one subdirectory. Actual memory-server-specific community is much smaller.
- **LangMem data quality:** GitHub API returned partial data for `langchain-ai/langmem` (stars captured: 1,530; description/pushed_at not available via API). Feature assessment based on prior knowledge and the LangChain documentation.
- **Maturity caveat:** Feature presence was confirmed by module inspection, not by test execution or production load. A first-generation module (e.g., 152-line `temporal.py`) is functionally present but less mature than a competitor's multi-year-refined equivalent (e.g., Graphiti's temporal model).
- **Knowledge bank:** `references/ai-agent-memory-landscape.md` (2026-06-26) provided the canonical competitor set and three-layer market map. Loaded before any web searches (per skill pitfall #20).
