# Architecture/Design Plan Inputs: Loom OS

> Generated 2026-07-01 | Post-parity analysis — all 9 roadmap features shipped. This file prepares the inputs for the `writing-plans` skill to generate full implementation plans.

## Project Context

- **Name:** Loom OS (package: `loom-os`, CLI: `loom`, repo: `agentic-os`)
- **Category:** AI agent memory fabric — knowledge graph platform for multi-agent coding
- **Platform:** Python daemon (FastAPI + SQLite + Graphify) + Next.js dashboard
- **Target market:** Developers and teams using multiple AI coding agents (Claude Code, Codex, Cursor, Hermes)
- **One-liner:** Unified agent memory fabric that weaves multiple AI coding agents into one shared, Graphify-powered knowledge graph per project.
- **Current state:** v0.2.0 on PyPI. 30 of 31 feature dimensions present. All 9 post-parity roadmap features shipped. 11 additional modules beyond the roadmap. Feature-complete for local-first single-agent and small-team use.

## Post-Parity Status

All 9 post-parity roadmap features (LLM extraction, hybrid search, PyPI ship, team mode, client SDK, agent discovery, benchmarks, plugins, LangChain integration) shipped as of commit `3b63a51`. The competitive question has shifted from "close the gap" (gap-closure is done — Loom leads 30:9 on the feature matrix) to "what's the next moat?".

**Module inventory (24 daemon modules, confirmed by introspection):**

| Module | LOC | Key Classes/Functions |
|--------|-----|----------------------|
| `api.py` | ~900+ | FastAPI app, lifespan, REST routes, WebSocket fan-out |
| `graph_engine.py` | ~400+ | `GraphEngine.build()`, `.hybrid_query()`, `._read_graph_json()` |
| `registry.py` | ~500+ | `AgentRegistry` (aiosqlite): agents, projects, tasks, capabilities |
| `router.py` | ~300+ | `Router.handle_file()`, `_handle_finding()`, `_handle_task()` |
| `watcher.py` | ~150+ | Watchdog observer → asyncio loop marshaling |
| `extractors.py` | ~250+ | `Extractor` ABC, `RegexExtractor`, `LLMExtractor`, `ExtractorPipeline` |
| `extracted_store.py` | ~50 | `ExtractedEdgeStore` sidecar JSON store |
| `embeddings.py` | 135 | `EmbeddingGenerator.embed()`, `.embed_batch()`, `EmbeddingStore` |
| `mcp_server.py` | 292 | `list_projects()`, `search_knowledge_graph()`, `query_graph()`, `add_to_memory()` |
| `worker.py` | 301 | `Worker` class, `run_claude()`, `run_agent()`, `_post_progress()` |
| `worktree.py` | 132 | `create_worktree()`, `commit_all()`, `branch_diff()`, `merge_branch()` |
| `temporal.py` | 152 | `TemporalFact`, `TemporalTracker.record()`, `.active_facts()`, `.timeline()` |
| `traces.py` | 159 | `TraceSpan`, `TraceCapture.start_span()`, `.finish_span()`, `.get_spans()` |
| `sessions.py` | 128 | `Session`, `SessionManager.start_session()`, `.add_context()` |
| `snapshots.py` | 126 | `StateSnapshot`, `SnapshotManager.capture()`, `.replay()` |
| `patterns.py` | 209 | `PatternRepository.observe()`, `.cross_project_patterns()`, `.top_patterns()` |
| `recall.py` | 163 | `RecallEngine.recall()`, `.retain()` |
| `ingest.py` | 176 | `DocumentIngestor.ingest_file()`, `.ingest_directory()` |
| `audit.py` | 155 | `AuditTrail.record()`, `.query()`, `.summary()` |
| `project_knowledge.py` | 265 | `discover_knowledge_sources()`, `ingest_all_sources()` |
| `known_agents.py` | 125 | `detect_installed()`, `get_known_agents()` |
| `shared_context.py` | 233 | `generate_shared_context()`, graph/findings/agent sections |
| `evals.py` | 195 | `EvalEngine.evaluate()`, `.get_pass_rate()`, `EvalCase` |
| `plugins.py` | ~100+ | Plugin discovery, `Extractor` contract |

## Competitive Constraints

Must-have features every competitor has — table stakes:
- **Hosted cloud option** (Cognee, Graphiti, Mem0, Letta, LangMem all have it; Loom does not) → see Suggestion 6 (Open Question)
- **Large community presence** (>20K stars for Cognee/Graphiti/Mem0; Loom is unmeasured publicly) → Suggestion 2 addresses this

Quality bars to meet or exceed:
- **Benchmark credibility** — no competitor has published comparison data; the opportunity is to be first
- **Module maturity** — Graphiti's temporal model has years of refinement; Loom's `temporal.py` is 152 lines. The bar is "battle-tested, not just present"

## Differentiation Strategy

**Primary differentiators (preserve and extend):**
1. **Filesystem inbox protocol** — zero-SDK, zero-auth agent onboarding. No competitor has this. It is Loom's deepest moat.
2. **Single-process daemon** — `pip install loom-os && loom start`. No Docker, no Neo4j, no Postgres. Architecturally alien to every competitor.
3. **Code-specific AST knowledge graph** — Graphify extracts real code structure. Competitors build graphs from unstructured text extraction.
4. **Dashboard + WebSocket push** — visual control plane with real-time updates. No memory competitor has a UI.

**Next-moat candidates (from suggestions):**
5. **Cross-project graph federation** (Suggestion 5) — category-defining capability no competitor is positioned to deliver
6. **Published benchmarks** (Suggestion 1) — marketing moat backed by the existing eval harness

## Architecture Implications

Each suggestion mapped to specific existing modules and methods. LOC estimates are approximate.

### Suggestion 1: Publish Benchmarks
- **Files:** Zero changes. Run existing `daemon/evals.py` (`EvalEngine.evaluate()`, `EvalCase`) and `benchmarks/` harness.
- **Output:** `BENCHMARKS.md` with reproducible results vs Cognee/Graphiti.
- **No daemon code changes needed.**

### Suggestion 2: Documentation Site + Community Channel
- **Files:** New `docs-site/` directory (static site). No daemon changes.
- **Community:** GitHub Discussions or Discord server — zero infrastructure.
- **No daemon code changes needed.**

### Suggestion 3: Incremental Graph Persistence
- **Modify:** `daemon/graph_engine.py` (~100–150 LOC)
  - Add `async incremental_update(self, project_path: str, changed_files: set[str]) -> None` alongside existing `_build()`
  - Diff changed files against cached parse results; merge new/modified nodes/edges into existing `graph.json`
  - Reuse `_read_graph_json()` for the existing graph state
- **Modify:** `daemon/watcher.py` (~20 LOC)
  - Pass changed-files set to the graph engine instead of triggering a full rebuild
  - The watcher already tracks which files changed via watchdog events — extend the event payload
- **Modify:** `daemon/router.py` (~10 LOC)
  - `Router._schedule_graph_update()` passes the changed-files set through to `graph_engine`
- **Test:** `tests/test_graph_engine.py` (~80 LOC)
  - Test: incremental update adds new nodes without removing existing ones
  - Test: modified file replaces its node's edges without affecting siblings
  - Test: deleted file removes its nodes from the graph
- **Constraint:** Graphify's own `graph.json` output must never be broken — incremental merges must produce equivalent results to full rebuilds for the changed subset.

### Suggestion 4: Mature First-Generation Modules
For each of the 5 modules, the pattern is: targeted edge-case tests + concurrency guards + defensive error handling.

- **`daemon/temporal.py` (152 → ~220 LOC):**
  - Add `asyncio.Lock` around `TemporalTracker.record()` and `.expire()` (concurrent fact recording)
  - Add `facts_at()` edge-case tests for boundary timestamps (exactly `valid_from`, exactly `valid_to`)
  - Add test: expired fact with no `valid_to` returns correctly
  - **Test:** `tests/test_temporal.py` (+~50 LOC)

- **`daemon/traces.py` (159 → ~210 LOC):**
  - Add guard in `TraceCapture.finish_span()` for span already finished (idempotent)
  - Add `_evict_oldest()` test for boundary: max_spans = 0, max_spans = 1
  - Add concurrency test: 100 simultaneous `start_span` calls don't exceed max_spans
  - **Test:** `tests/test_traces.py` (+~40 LOC)

- **`daemon/sessions.py` (128 → ~180 LOC):**
  - Add try/except in `SessionManager._bridge_to_inbox()` for mailbox write failures
  - Add test: session context survives daemon restart (persistence check)
  - Add test: `end_session()` cleans up subgraph correctly
  - **Test:** `tests/test_sessions.py` (+~40 LOC)

- **`daemon/snapshots.py` (126 → ~180 LOC):**
  - Add guard in `SnapshotManager.replay()` for partial/corrupt snapshots
  - Add test: `capture()` + `replay()` roundtrip preserves all state fields
  - Add test: eviction policy keeps most-recent N snapshots
  - **Test:** `tests/test_snapshots.py` (+~40 LOC)

- **`daemon/patterns.py` (209 → ~270 LOC):**
  - Expand `_normalise()` with more linguistic coverage (stemming, common abbreviations)
  - Add test: `cross_project_patterns()` correctly deduplicates across projects
  - Add test: `deprecate()` transitions status correctly
  - **Test:** `tests/test_patterns.py` (+~40 LOC)

- **Total:** ~250 LOC new code + ~210 LOC new tests across 5 modules

### Suggestion 5: Cross-Project Graph Federation
- **Create:** `daemon/federation.py` (~120 LOC)
  ```python
  class FederatedIndex:
      def __init__(self, loom_dir: str = "~/.loom"): ...
      async def build_index(self) -> dict: ...  # scan all graphify-out/graph.json
      async def query(self, question: str, depth: int = 2) -> list[dict]: ...  # returns {node, project, distance}
      async def cross_project_references(self, symbol: str) -> list[dict]: ...  # which projects use this?
  ```
- **Modify:** `daemon/api.py` (+~30 LOC)
  - `GET /api/federated-query?q=...&depth=2` → federated search results
  - `GET /api/federated/references?symbol=...` → cross-project symbol lookup
- **Create:** `dashboard/components/federation-explorer.tsx` (~150 LOC)
  - Search component showing results tagged by project origin
  - Click-through to the specific project's graph view
- **Test:** `tests/test_federation.py` (~60 LOC)
  - Test: two projects with shared nodes appear in federated query
  - Test: cross_project_references finds a symbol in multiple repos
- **Constraint:** Must not break per-project isolation — federation is read-only across projects. No project can write to another's graph.

### Suggestion 7: MCP Ecosystem Positioning
- **Modify:** `daemon/mcp_server.py` (+~60 LOC)
  - Add `discover_agents(project: str)` tool — wraps `registry.list_agents_by_project()`
  - Add `query_temporal_facts(project: str, timestamp: str = None)` tool — wraps `TemporalTracker.active_facts()` / `.facts_at()`
  - Add `search_patterns(project: str, query: str)` tool — wraps `PatternRepository.list_patterns()`
  - All read-only; no new infrastructure needed
- **Test:** `tests/test_mcp.py` (+~30 LOC)

### Suggestion 8: Framework Integrations
- **Create:** `integrations/llamaindex-loom/` (~200 LOC + `pyproject.toml` + tests + README)
  - Implements LlamaIndex storage backend interface
  - Delegates to `loom-client` for all I/O
  - Pattern proven with `langchain-loom` (commit d13667c)
- **Create:** `integrations/crewai-loom/` (~200 LOC + same package structure)
  - Implements CrewAI shared memory interface
  - Delegates to `loom-client`
- **No daemon changes.** Both packages use `loom-client` as their transport.

### Suggestion 9: Expanded Plugin Examples
- **Create:** `examples/plugins/git_history.py` (~50 LOC) — extracts entities from git log
- **Create:** `examples/plugins/todo_scanner.py` (~40 LOC) — scans for TODO/FIXME/HACK comments
- **Create:** `examples/plugins/test_coverage.py` (~50 LOC) — maps test files to source files
- **Create:** `examples/plugins/dependency_mapper.py` (~50 LOC) — extracts import dependency edges
- **No daemon changes.** Plugins follow the existing `Extractor` ABC and `plugins.discover()` mechanism.

## Open Questions

These require a user decision before planning can proceed:

1. **Cloud offering: Option A (ship managed) or Option B (self-hosted positioning)?**
   - Option A: Dockerize + optional Postgres backend (~150 LOC). Captures enterprise buyers who ask "is there a cloud version?"
   - Option B: Lean into local-first philosophy. Write a position paper. Zero code changes.
   - **This is a strategic/business decision, not a technical one. The user should decide.**

2. **Priority ordering: benchmarks first or docs first?**
   - Both are P0. Benchmarks take ~2 hours to run + write up (harness exists). Docs site takes ~2 days to deploy + write content.
   - Recommendation: benchmarks first (higher leverage, less effort), then docs.

3. **Which P1 module to harden first?**
   - `temporal.py` is the most competitive (Graphiti is the benchmark). Starting here gives the strongest "we match Graphiti" claim.
   - `patterns.py` is the most differentiating (no competitor has cross-project patterns). Starting here strengthens the unique-value claim.

4. **Federation privacy model:**
   - Cross-project federation surfaces symbols across all projects in `~/.loom/`. For team mode, should federation be per-user only, or organization-wide? This affects the federation index scoping.

## Recommended Next Step

Load the `writing-plans` skill with this file as context. The recommended implementation order is:

1. **Immediate P0 (days):** Run benchmarks (Suggestion 1) + deploy docs site (Suggestion 2). Both are primarily execution work, not new code.
2. **Next P1 (weeks):** Incremental graph persistence (Suggestion 3) — highest technical leverage, prevents scaling problems. Then module maturity hardening (Suggestion 4) starting with `temporal.py`.
3. **Then P1 differentiator:** Cross-project federation (Suggestion 5) — category-defining capability.
4. **Strategic gate:** Cloud offering decision (Suggestion 6) must be resolved before any cloud-related work.
5. **Background P2-P3:** MCP expansion (Suggestion 7), framework integrations (Suggestion 8), plugin examples (Suggestion 9).

**Design context to read:**
- `docs/plans/2026-06-29-post-parity-roadmap-implementation.md` — the roadmap that shipped all 9 features. Its Phase 3 section called for re-running this analysis before proceeding. That's what we just did.
- `docs/ARCHITECTURE.md` — current module map and data flow.
- `CLAUDE.md` — project conventions, daemon patterns, and gotchas.
