# Competitor Analysis Suggestions: Loom OS

> Generated 2026-07-01 | Post-parity analysis — all 9 roadmap features shipped. These suggestions are forward-looking, not gap-closure.

## Context

All 9 post-parity roadmap features (LLM extraction, relational queries, PyPI ship, team mode, client SDK, agent discovery, benchmarks, plugins, LangChain integration) shipped as of commit `3b63a51` (2026-06-29). Additionally, 11 modules beyond the roadmap shipped (temporal, traces, sessions, snapshots, patterns, recall, ingest, audit, project_knowledge, known_agents, shared_context). Loom now has 30 of 31 feature dimensions — the next-closest competitor has 9.

**The competitive frame has shifted from "close the gap" to "build the next moat."** These suggestions reflect that.

---

## Completed Suggestions (from 2026-06-26 analysis)

| # | Original Suggestion | Status | Shipped Commit |
|---|-------------------|--------|----------------|
| ✅1 | LLM extraction pipeline (Ollama/OpenAI/Claude) | **Shipped** | 5671410, f66c7df |
| ✅2 | Relational/hybrid query support | **Shipped** | 4ed7743, 781cf12 |
| ✅3 | Ship to PyPI + `loom init` CLI | **Shipped** | 7c07c64, 5e14b3c, 2c8ba3f |
| ✅4 | Team mode (optional auth, per-user inbox) | **Shipped** | ea595cc, 30b237f |
| ✅5 | Client SDK (Python + npm TypeScript) | **Shipped** | 884d7ca |
| ✅6 | Agent discovery / capability directory | **Shipped** | 6c1311b |
| ✅7 | Performance benchmarks & eval harness | **Shipped** | 4d5fba3 |
| ✅8 | Plugin system for extractors | **Shipped** | 64eeea8 |
| ✅9 | Framework integrations (LangChain BaseMemory) | **Shipped** | d13667c |

---

## New Suggestions

### Suggestion Priority Legend

| Priority | What it means for Loom *now* |
|----------|------------------------------|
| **P0** | Distribution & community — the binding constraint. The product is feature-complete; discoverability is the bottleneck. |
| **P1** | Maturity hardening — make first-generation modules battle-tested enough to compete with specialists. |
| **P2** | Go-to-market positioning — cloud offering decision, MCP ecosystem play. |
| **P3** | Ecosystem expansion — more integrations, more content, polish. |

---

## P0: Distribution & Community Growth

### Suggestion 1: Publish Reproducible Benchmarks

**Priority:** P0
**Evidence:** The eval harness (`daemon/evals.py` — 195 lines with `EvalEngine`, `EvalCase`, LLM-as-judge scoring) and benchmark runner (commit 4d5fba3 with `benchmarks/` harness) exist but have never been run head-to-head against Cognee or Graphiti. No competitor has published comparison data.
**Rationale:** Loom's single-process/SQLite/NumPy architecture is a radical bet against the Docker+Neo4j orthodoxy. Proving it wins on latency, setup time, and resource consumption — with reproducible numbers — is the single highest-leverage marketing asset available. Cognee (26K stars) and Graphiti (28K stars) can't counter with their own numbers because their infrastructure overhead is structurally higher.
**Action:** Run the existing benchmark harness against Loom + Cognee + Graphiti on identical tasks (graph build time, query latency, recall precision on a standard repo). Publish results as `BENCHMARKS.md` with reproducible setup instructions. Zero new code needed — the harness exists.
**Architecture impact:** None — run existing `benchmarks/` harness. Output is a markdown report.

---

### Suggestion 2: Documentation Site + Community Channel

**Priority:** P0
**Evidence:** Loom has 31 feature dimensions, 24 daemon modules, a Next.js dashboard, Python + npm SDKs, MCP server, and LangChain integration — but no documentation site and no community channel (Discord/GitHub Discussions). Cognee and Mem0 both have active Discord servers that drive community growth.
**Rationale:** The product is deep — graph-based memory, autonomous worker execution, temporal tracking, pattern detection. Discoverability is now the binding constraint, not features. A developer landing on the GitHub repo sees 24 Python modules and a dashboard — that's intimidating without guided documentation.
**Action:** (1) Deploy a docs site (MkDocs or Fumadocs — the dashboard already uses Next.js, so Fumadocs is natural). (2) Open a GitHub Discussions tab or Discord server. (3) Write 3-5 tutorial walkthroughs: "connect Claude Code to Loom", "add a custom extractor plugin", "use hybrid search for architecture Q&A". (4) Create 1-2 demo projects showing the full inbox → graph → dashboard flow.
**Architecture impact:** None for the daemon. Docs site is a separate static deployment. Discord/GitHub Discussions is zero infrastructure.

---

## P1: Maturity Hardening

### Suggestion 3: Incremental Graph Persistence

**Priority:** P1
**Evidence:** `daemon/graph_engine.py` invokes `graphify` as a subprocess that rebuilds `graph.json` from the project's full AST on each update. The mtime cache (commit 4d5fba3) skips unnecessary rebuilds, but when a rebuild does happen, it's full-source. Cognee and Graphiti use Neo4j which handles incremental updates natively — changed nodes merge without full rebuild.
**Rationale:** Loom currently rate-limits graph updates to 1 per 30 seconds per project (`MIN_UPDATE_INTERVAL` in router.py). This works for small projects but becomes a scaling bottleneck on large monorepos or many concurrent projects. Incremental updates — diff changed files against the last parse and merge only new/modified nodes/edges into `graph.json` — would eliminate this bottleneck before it becomes a complaint.
**Action:** Modify `graph_engine.py`'s build method to accept a set of changed file paths (from the watcher) and pass only those to Graphify's incremental mode (if available), or diff the new `graph.json` against the cached one and merge new/modified nodes. Add corresponding tests in `tests/test_graph_engine.py`.
**Architecture impact:**
- `daemon/graph_engine.py` (~100–150 LOC change: add `incremental_update()` method alongside `_build`)
- `daemon/watcher.py` (~20 LOC: pass changed-files set instead of full project path)
- `tests/test_graph_engine.py` (~80 LOC: new test for incremental merge correctness)

---

### Suggestion 4: Mature First-Generation Modules

**Priority:** P1
**Evidence:** Several modules are first-generation implementations under 210 lines that are present in the feature matrix but not yet production-hardened:

| Module | LOC | Maturity Concern |
|--------|-----|------------------|
| `temporal.py` | 152 | Validity-range fact tracking — Graphiti has years of refinement in temporal graphs |
| `traces.py` | 159 | Span capture with eviction — needs concurrency safety under load |
| `sessions.py` | 128 | Session subgraphs — `_bridge_to_inbox` needs error handling for mailbox failures |
| `snapshots.py` | 126 | State snapshots — `replay()` needs guard against partial snapshots |
| `patterns.py` | 209 | Cross-project patterns — `_normalise()` needs more linguistic coverage |

**Rationale:** The feature matrix shows ✅ for these modules, and they are functionally present. But "present" and "battle-tested" are different claims. Before any public claim about temporal tracking or execution tracing, these modules need edge-case tests, concurrency guards, and eviction policies validated under load. The risk: if a user tries `temporal.facts_at(timestamp)` and gets a wrong answer because of an edge case, it undermines the credibility of the entire platform.
**Action:** For each module: (1) write targeted edge-case tests in the existing `tests/test_*.py` files; (2) add concurrency guards (`asyncio.Lock` where state mutations happen); (3) add eviction policy tests under load; (4) expand the module by 50–100 LOC of defensive guards.
**Architecture impact:** Expand each of the 5 modules by ~50–100 LOC. Extend existing test files (no new test files needed). Total: ~250–500 LOC across daemon + ~300–500 LOC across tests.

---

### Suggestion 5: Cross-Project Graph Federation

**Priority:** P1
**Evidence:** Projects are fully isolated — each has its own `~/.loom/inbox/<project>/graphify-out/graph.json`. There is no way to query "which projects use pattern X?" or "find this module across all repos." `patterns.py:cross_project_patterns()` works on pattern observations (textual), not on graph federation. No competitor has cross-project graph queries either — they all use flat namespaces.
**Rationale:** This is a category-defining capability no competitor is positioned to deliver. A `federation.py` module that indexes across all `graphify-out/` directories would unlock "find pattern X across the org's repos" — something that currently requires running separate searches per project. For teams with multiple microservices, this is the difference between "memory per project" and "organizational knowledge graph."
**Action:** Create `daemon/federation.py` that builds a combined index of nodes/edges across all project graphs. Add `GET /api/federated-query?q=...` endpoint. Add a dashboard component for federated search results.
**Architecture impact:**
- New `daemon/federation.py` (~120 LOC: scan all `~/.loom/inbox/*/graphify-out/graph.json`, build merged adjacency)
- `daemon/api.py` (+~30 LOC: `GET /api/federated-query` endpoint)
- `dashboard/components/federation-explorer.tsx` (~150 LOC: new search component)
- `tests/test_federation.py` (~60 LOC: test merged index correctness)

---

## P2: Go-To-Market Positioning

### Suggestion 6: Cloud/Hosted Offering Decision

**Priority:** P2
**Evidence:** Every competitor with >20K stars has a hosted option (Cognee Cloud, Zep Cloud, Mem0 Cloud, Letta Cloud, LangGraph Cloud). Loom is the only major competitor without one. At the same time, Loom's single-process architecture makes containerization *easier* than competitors — it's one `docker run` vs Cognee's docker-compose with Neo4j + PGVector.
**Rationale:** This is a go-to-market decision, not an architecture one. Enterprise buyers ask "is there a cloud version?" before evaluating features. The answer doesn't have to be "yes" — but it has to be a deliberate choice, not silence. Either:
- **Option A:** Ship a managed offering. Dockerize the daemon (trivial for single-process), offer multi-tenant isolation via the existing team-mode per-user inbox scoping, optionally swap SQLite for Postgres for multi-tenant durability.
- **Option B:** Lean into "self-hosted by design" positioning. Make the case that single-process local-first is a feature, not a limitation — "your agent memory never leaves your machine."
**Action:** Make an explicit decision and document it. If Option A: write `Dockerfile` + `docker-compose.yml` (~50 LOC total for single-process), add optional Postgres connection string support to `registry.py`. If Option B: write a position paper explaining the local-first philosophy.
**Architecture impact:**
- Option A: `Dockerfile` (~20 LOC) + `docker-compose.yml` (~30 LOC) + optional `daemon/registry.py` Postgres backend (~100 LOC behind a connection-string check)
- Option B: documentation only

---

### Suggestion 7: MCP Ecosystem Positioning

**Priority:** P2
**Evidence:** Loom has `mcp_server.py` (292 lines) exposing 4 tools (`list_projects`, `get_project_graph`, `search_knowledge_graph`, `add_to_memory`). The MCP ecosystem is the fastest-growing agent protocol (87K-star umbrella repo). The official MCP Memory Server is entity-relation only — no code awareness, no graph search, no dashboard.
**Rationale:** Positioning Loom as "the richest MCP-compatible memory backend" opens a distribution channel through the MCP ecosystem. Any agent that speaks MCP can use Loom as its memory layer — Claude Code, Cursor, Windsurf, and any future MCP-compatible tool. This is the cheapest distribution play available: a few more MCP tools cost ~60 LOC but expose Loom to the entire MCP-compatible agent ecosystem.
**Action:** Add 2-3 more MCP tools to `mcp_server.py`: agent discovery, temporal fact queries, pattern search. Update the MCP server documentation to position Loom as a drop-in upgrade from the basic MCP Memory Server.
**Architecture impact:** `daemon/mcp_server.py` (+~60 LOC: 2-3 new tool functions). No daemon changes needed — the tools query existing modules.

---

## P3: Ecosystem Expansion

### Suggestion 8: Additional Framework Integrations (LlamaIndex, CrewAI)

**Priority:** P3
**Evidence:** Loom has `langchain-loom` (LangChain `BaseMemory` integration). The roadmap (Feature #10) also called for LlamaIndex and CrewAI integrations. LlamaIndex has a storage backend interface; CrewAI has shared crew memory needs. Both are thin wrappers over `loom-client`.
**Rationale:** Each integration opens a community's discoverability channel. LangChain's ecosystem is the largest; LlamaIndex's is second for RAG use cases; CrewAI is growing in multi-agent orchestration. The pattern is proven with `langchain-loom` — replicate it.
**Action:** Create `integrations/llamaindex-loom/` (implements LlamaIndex storage backend) and `integrations/crewai-loom/` (implements CrewAI shared memory). Each is a separate package (~200 LOC) delegating to `loom-client`.
**Architecture impact:** 2 new packages under `integrations/`, each ~200 LOC + tests + README. No daemon changes.

---

### Suggestion 9: Expanded Plugin Examples & Plugin Marketplace

**Priority:** P3
**Evidence:** The plugin system shipped with 3 example plugins (commit 64eeea8) and a `/api/plugins` endpoint. The plugin discovery mechanism (`daemon/plugins.py`) works but has a small example set.
**Rationale:** The plugin system is the community contribution surface. More high-quality example plugins (Git history extractor, TODO/FIXME scanner, test coverage analyzer, dependency graph mapper) demonstrate the platform's extensibility and seed the ecosystem. A community-contributed plugin registry would be a moat — competitors don't have one.
**Action:** Write 3-5 additional example plugins. Document the `Extractor` contract thoroughly. Consider a `loom plugins install <url>` command for remote plugin installation (trust boundary: local filesystem only, documented).
**Architecture impact:** Example plugins are new files under `examples/plugins/` (~50 LOC each). Optional `daemon/plugins.py` enhancement for remote install (~40 LOC).

---

## Summary Matrix

| # | Suggestion | Priority | Evidence Strength | Architecture Impact |
|---|-----------|----------|-------------------|---------------------|
| 1 | Publish reproducible benchmarks | P0 | Strong (harness exists, no competitor has published) | Zero — run existing code |
| 2 | Documentation site + community channel | P0 | Strong (31 features, zero discoverability surface) | None (separate deployment) |
| 3 | Incremental graph persistence | P1 | Strong (Graphify full-rebuild is a known scaling bottleneck) | ~250 LOC in graph_engine + watcher + tests |
| 4 | Mature first-generation modules | P1 | Strong (5 modules under 210 LOC, untested at scale) | ~500 LOC across 5 modules + tests |
| 5 | Cross-project graph federation | P1 | Strong (category-defining — no competitor has it) | ~360 LOC new federation module + endpoint + dashboard |
| 6 | Cloud/hosted offering decision | P2 | Strong (every competitor has one; deliberate choice needed) | ~50 LOC (Dockerfile) or zero (positioning only) |
| 7 | MCP ecosystem positioning | P2 | Moderate (MCP server exists, needs more tools + messaging) | ~60 LOC in mcp_server.py |
| 8 | LlamaIndex + CrewAI integrations | P3 | Moderate (proven pattern with langchain-loom) | 2 packages × ~200 LOC each |
| 9 | Expanded plugin examples | P3 | Moderate (plugin system exists, needs more seeds) | ~250 LOC examples + optional CLI enhancement |

---

## Next Steps

1. **Immediate (P0):** Run the benchmark harness against Cognee/Graphiti and publish results. Deploy a docs site. Open a community channel.
2. **Next quarter (P1):** Incremental graph persistence, module maturity hardening, cross-project federation.
3. **Strategic decision needed:** Cloud offering — make an explicit choice and document it.
4. **Ongoing (P2-P3):** MCP ecosystem expansion, framework integrations, plugin ecosystem growth.
5. Use `plan-inputs.md` as input to the `writing-plans` skill for full implementation planning.
