# Architecture/Design Plan Inputs: Loom OS

## Project Context

- **Name:** Loom OS
- **Category:** AI agent memory fabric / knowledge graph platform / multi-agent coordination tool
- **Platform:** macOS/Linux daemon (Python/FastAPI) + web dashboard (Next.js 16)
- **Target market:** Engineering teams using multiple AI coding agents (Claude Code, Codex, Hermes, Gemini CLI, Copilot CLI, Aider)
- **One-line description:** Unified agent memory fabric that weaves multiple AI coding agents into one shared, Graphify-powered knowledge graph per project. Agents talk through the filesystem; a Next.js dashboard is the control plane.
- **Package:** `loom-os` on PyPI, CLI command `loom`, repo directory `agentic-os`

## Competitive Constraints

### Must-have features (from P0 suggestions)
- **Production vector backend** — embeddings must persist across daemon restarts and scale beyond ~10K documents. Cognee sets this bar with PGVector/Qdrant.
- **Temporal fact persistence** — temporal queries must survive restarts. Graphiti sets this bar with Neo4j.
- **Session checkpoint persistence** — session context must survive crashes/restarts. Letta sets this bar with tiered memory persistence.

### Quality bars to meet or exceed
- **Vector search latency:** Cognee achieves <100ms on 10K+ docs via PGVector indexing. Loom's in-memory scan is O(n) — fine for <1K but degrades.
- **Temporal query accuracy:** Graphiti's bi-temporal model supports point-in-time and range queries. Loom's `facts_at(time)` is in-memory only.
- **SDK resilience:** Mem0's SDKs handle network failures with retry + backoff. Loom's SDKs are basic HTTP wrapping.

### Pricing/deployment expectations
- All major competitors (Cognee, Mem0, Letta) offer managed cloud. Loom is local-only.
- Self-hosted Docker is table stakes for team usage.

## Differentiation Strategy

### Primary differentiator
**Filesystem inbox protocol + three-layer span.** No competitor offers both zero-SDK integration (drop files, no API key) AND the full memory→orchestration→dashboard stack in a single process.

### Secondary differentiators
1. **Code-specific knowledge graph** — Graphify extracts AST-level structure. No general memory tool understands code.
2. **Multi-agent worker execution** — Loom runs 6 different agent CLIs in isolated git worktrees. No memory competitor does this.
3. **Eval harness + pattern repository** — unique in this category. No competitor has either.
4. **MCP server** — Loom speaks the MCP protocol natively, competing with MCP Memory Server on its own turf while offering strictly more.
5. **Plugin system** — community extractors via `~/.loom/plugins/extractors/`. Cognee has a partial pipeline extension mechanism.

## Architecture Implications

### P0: Production Vector Backend
- **Feature:** Persistent vector storage replacing in-memory NumPy
- **Component:** New `daemon/vec_store.py` module (~120 LOC)
- **Modify:** `EmbeddingStore` class in `daemon/embeddings.py` (~30 LOC changed — swap `_docs` list for sqlite-vec table)
- **Migration:** On first startup after upgrade, re-embed from existing findings (or accept a cold start — embeddings are derived data)
- **Dependency:** `sqlite-vec` Python package (pure C extension, no server) or `lancedb` (columnar ANN)
- **API impact:** None — `EmbeddingStore.insert()` and `.search()` signatures unchanged
- **LOC estimate:** ~150 LOC total

### P0: Temporal Fact Persistence
- **Feature:** SQLite-backed temporal fact storage
- **Component:** Modify `daemon/temporal.py` (~80 LOC added)
- **Change:** `TemporalTracker.__init__` accepts `db_path` parameter (default: `~/.loom/temporal.db`). Add `CREATE TABLE temporal_facts` schema. `record()` and `expire()` write to SQLite. `active_facts()`, `list_facts()`, `timeline()`, `facts_at()` query from SQLite.
- **Migration:** None needed — empty table on first run. Facts accumulate going forward.
- **API impact:** None — all temporal API endpoints continue to work (they call TemporalTracker methods)
- **LOC estimate:** ~80 LOC

### P0: Session Checkpoint Persistence
- **Feature:** SQLite-backed session storage with checkpoint/restore
- **Component:** Modify `daemon/sessions.py` (~60 LOC added)
- **Change:** Add `sessions` table. `SessionManager` stores sessions in SQLite. Add `checkpoint(session_id)` and `restore(session_id)` methods. `start_session()` checks for existing checkpoint.
- **Migration:** None — empty table on first run.
- **API impact:** New `POST /api/sessions/{id}/checkpoint` and `POST /api/sessions/{id}/restore` endpoints (~20 LOC in api.py)
- **LOC estimate:** ~80 LOC

### P1: Managed Cloud / Dockerization
- **Feature:** Docker deployment + HTTP-to-inbox gateway
- **Component:** New `Dockerfile` + `docker-compose.yml` (~50 LOC)
- **Component:** New HTTP-to-inbox middleware in `daemon/api.py` (~100 LOC) — translate `POST /api/inbox/{project}/finding` to writing a `finding-*.md` file
- **Dependency:** None new for Docker. Multi-tenant requires schema changes in `registry.py` (~50 LOC — add `tenant_id` column)
- **LOC estimate:** ~200 LOC

### P1: Multi-Modal Query Planner
- **Feature:** Replace BFS heuristic with scored query planner
- **Component:** Refactor `hybrid_query()` in `daemon/graph_engine.py` (~100 LOC changed)
- **Change:** (1) Pre-compute node embeddings at graph build time and cache. (2) Use ANN search for seed selection instead of brute-force cosine. (3) Replace BFS with scored ranking combining semantic similarity + structural distance + relational edge weight.
- **Dependency:** Depends on P0 vector backend for embedding persistence (otherwise re-computing embeddings per query defeats the purpose)
- **LOC estimate:** ~100 LOC

### P2: Framework Adapters (AutoGen, CrewAI)
- **Feature:** `loom-autogen` and `loom-crewai` packages
- **Component:** New `integrations/loom-autogen/` (~100 LOC) and `integrations/loom-crewai/` (~100 LOC)
- **Pattern:** Same as existing `langchain-loom` — subclass framework's memory base class, delegate to Loom REST API
- **LOC estimate:** ~200 LOC total

### P2: Production Auth (OAuth2 + RBAC)
- **Feature:** OAuth2 password flow + role-based access control
- **Component:** Modify `daemon/auth.py` (~150 LOC added)
- **Change:** Add OAuth2 backend (passlib + python-jose). Add `roles` and `user_roles` tables to registry. Add role checks on mutating API routes.
- **LOC estimate:** ~200 LOC

### P2: Mature SDKs
- **Feature:** Retry, batching, streaming for Python + npm SDKs
- **Component:** Modify `loom-client/` (~80 LOC) and `loom-client-ts/` (~80 LOC)
- **Change:** Add tenacity-based retry. Add batch methods. Add SSE consumer for task progress.
- **LOC estimate:** ~160 LOC

## Open Questions

1. **Vector backend choice:** sqlite-vec (minimal, pure extension) vs LanceDB (columnar ANN, more features but heavier dependency)? The plugin system already exists — could the vector backend be pluggable?
2. **Temporal persistence scope:** Sidecar SQLite file (`~/.loom/temporal.db`) vs extending `state.db` in registry.py? Sidecar keeps temporal logic isolated; state.db consolidation simplifies backups.
3. **Multi-tenant isolation model:** Separate databases per tenant vs `tenant_id` column on every table? Column approach is simpler but requires audit discipline; database-per-tenant is safer but operationally heavier.
4. **Query planner vs incremental improvement:** Replace `hybrid_query` entirely or incrementally improve the existing BFS? Incremental is lower risk; full replacement is cleaner.
5. **Auth scope:** Is OAuth2 sufficient, or do enterprise deployments need OIDC/SAML? Depends on target customer (SMB vs enterprise).
6. **Should the eval harness be a standalone tool?** Deepening it might warrant extracting to a separate `loom-eval` package rather than growing `daemon/evals.py`.

## Recommended Next Step

Load the `writing-plans` or `plan` skill with this file as context to generate the full implementation plan. The P0 items (vector backend, temporal persistence, session persistence) are the highest-value changes — they convert three V1 in-memory implementations to production-grade and close the depth gap with Cognee and Graphiti. They're also independent of each other and can be implemented in parallel.
