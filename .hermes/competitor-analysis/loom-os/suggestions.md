# Competitor Analysis Suggestions: Loom OS

## Suggestion: Production Vector Backend

**Priority:** P0 (must-have)
**Evidence:** Cognee ships PGVector + Qdrant as production vector backends. Loom's `EmbeddingStore` (`daemon/embeddings.py`, 135 lines) uses in-memory NumPy arrays with zero-vector graceful degradation. Embeddings are lost on daemon restart. The code comments: "For <10K documents this is fast and requires zero infrastructure. A future V2 can swap to an on-disk sqlite-vec backend without changing the public API."
**Rationale:** Semantic search across findings, entities, and graph nodes is a core feature. Without persistence, every daemon restart requires re-embedding the entire corpus. For teams with >10K findings/documents, the in-memory store won't scale.
**Action:** Replace `EmbeddingStore._docs` (in-memory list) with a sqlite-vec table in `~/.loom/embeddings.db`. The existing `EmbeddingStore` API (`insert`, `search`) stays identical — only the storage backend changes. Consider LanceDB as an alternative if ANN index performance matters.
**Architecture impact:** New `daemon/vec_store.py` module (~120 LOC) + modify `EmbeddingStore` class in `embeddings.py` (~30 LOC changed) + migration path for any existing in-memory embeddings.

---

## Suggestion: Temporal Fact Persistence

**Priority:** P0 (must-have)
**Evidence:** Graphiti / Zep persists temporal facts to Neo4j — bi-temporal queries survive restarts. Loom's `TemporalTracker` (`daemon/temporal.py`, 152 lines) stores facts in `self._facts: dict[str, TemporalFact]` — an in-memory dict. The docstring explicitly says "All state is in-memory (V1). SQLite persistence can be added later."
**Rationale:** Temporal queries ("what was true at time T?") are useless if facts disappear on restart. This is a core differentiator vs Graphiti and it's currently non-functional across sessions.
**Action:** Modify `TemporalTracker.__init__` to accept a `db_path` parameter and add SQLite schema (`temporal_facts` table with columns matching `TemporalFact` dataclass). Persist `record()` and `expire()` calls to SQLite. Load facts on startup.
**Architecture impact:** Modify `daemon/temporal.py` (~80 LOC added) + add temporal table to `registry.py` initialization or use a sidecar SQLite file. ~210 lines total after change.

---

## Suggestion: Session Checkpoint Persistence

**Priority:** P0 (must-have)
**Evidence:** Letta persists agent state (working memory + archival storage) across restarts. Loom's `SessionManager` (`daemon/sessions.py`, 128 lines) stores sessions in `self._sessions: dict[str, Session]` — in-memory only. The docstring says: "Sessions are in-memory (V1). A future V2 can persist session checkpoints to disk for crash recovery."
**Rationale:** Long-running agent sessions that span daemon restarts (e.g., after a crash or update) lose all accumulated context. For multi-agent workflows where session continuity matters, this is a reliability gap.
**Action:** Add SQLite-backed session storage. Serialize `Session.context` dict as JSON. Add `checkpoint()` and `restore()` methods.
**Architecture impact:** Modify `daemon/sessions.py` (~60 LOC added). Add `sessions` table to registry or sidecar DB.

---

## Suggestion: Managed Cloud Deployment

**Priority:** P1 (high)
**Evidence:** Cognee, Mem0, and Letta all offer managed cloud options. Loom OS is local-only (`pip install loom-os`).
**Rationale:** Teams that don't want to manage a local daemon need a hosted option. The filesystem inbox protocol is inherently local — a cloud version would need an API gateway that translates HTTP → inbox files internally.
**Action:** (1) Dockerize the daemon + dashboard as a single container for self-hosted teams. (2) Design an HTTP-to-inbox gateway for managed cloud (agents POST findings → gateway writes to inbox → daemon processes as normal). (3) Add SSO/OAuth for multi-tenant cloud.
**Architecture impact:** New `Dockerfile` + `docker-compose.yml` (~50 LOC). HTTP-to-inbox gateway as a new FastAPI middleware (~100 LOC). Multi-tenant schema changes to `registry.py` (~50 LOC).

---

## Suggestion: Multi-Modal Query Planner (Upgrade from BFS Heuristic)

**Priority:** P1 (high)
**Evidence:** Cognee has a proper multi-modal query planner across graph + vector + relational stores. Loom's `hybrid_query` (`daemon/graph_engine.py:275-329`) is a vector-seeded BFS over AST + extracted edges — a heuristic join, not a true query planner.
**Rationale:** The BFS approximation degrades on large graphs (every BFS step recomputes embeddings for the current node). A scored query planner that pre-computes embeddings and uses ANN search would be both faster and more accurate.
**Action:** (1) Pre-compute and cache embeddings for all node IDs (avoid recomputing per BFS step). (2) Replace BFS traversal with a scored ranking that combines semantic similarity + structural distance + relational edge weight. (3) Add query plan explainability (show which sources contributed to each result).
**Architecture impact:** Refactor `hybrid_query` in `graph_engine.py` (~100 LOC changed). Depends on P0 vector backend for embedding persistence.

---

## Suggestion: Expand Framework Adapter Ecosystem

**Priority:** P2 (medium)
**Evidence:** Mem0 has mature adapters for LangChain, AutoGen, and CrewAI. Loom has a LangChain `BaseMemory` adapter only (`langchain-loom` integration, commit d13667c).
**Rationale:** Framework adapters are the primary integration path for teams already using agent frameworks. Each adapter expands Loom's addressable market.
**Action:** Add `loom-autogen` adapter (AutoGen conversable agent memory). Add `loom-crewai` adapter (CrewAI crew memory). Both follow the same pattern as the LangChain adapter — subclass the framework's memory base class and delegate to Loom's API.
**Architecture impact:** New packages (~100 LOC each). No daemon changes needed — the REST API already supports all required operations.

---

## Suggestion: Production Authentication (OAuth2 + RBAC)

**Priority:** P2 (medium)
**Evidence:** Loom's auth is optional token middleware (`daemon/auth.py`, commit ea595cc: "no-op when unconfigured"). Mem0 and Letta have production auth with managed cloud.
**Rationale:** For team usage and any future cloud deployment, token middleware isn't sufficient. OAuth2 enables SSO, and RBAC enables per-role permissions (admin, developer, viewer).
**Action:** (1) Add OAuth2 password flow (or OIDC for enterprise SSO). (2) Add role-based access control on API routes (admin can delete projects, developer can dispatch tasks, viewer is read-only). (3) Add per-user project isolation (partially implemented via the `user` column in the agents table).
**Architecture impact:** Modify `daemon/auth.py` (~150 LOC added). Add `roles` and `permissions` tables to `registry.py`. Add auth middleware to all mutating API routes.

---

## Suggestion: Mature Client SDKs (Retry, Batching, Streaming)

**Priority:** P2 (medium)
**Evidence:** Mem0's SDKs include retry logic, request batching, and streaming responses. Loom's Python SDK (`loom-client`) and npm twin are basic HTTP wrapping.
**Rationale:** Production usage requires resilience patterns — transient failures, bulk operations, and progress streaming for long-running tasks.
**Action:** (1) Add exponential backoff retry to all SDK methods. (2) Add batch methods (`add_findings_batch`, `search_batch`). (3) Add SSE/streaming for task progress (the daemon already has `POST /tasks/{id}/progress` — expose it as a stream).
**Architecture impact:** Modify `loom-client/` Python package (~80 LOC). Modify npm twin `loom-client-ts/` (~80 LOC). No daemon changes.

---

## Suggestion: Cross-Project Pattern Mining (Deepen Existing Feature)

**Priority:** P3 (nice-to-have)
**Evidence:** Loom's `daemon/patterns.py` (209 lines) already has a `cross_project` search endpoint (`GET /api/patterns/cross-project`). No competitor has any pattern repository at all.
**Rationale:** This is a unique differentiator that's underexploited. Cross-project pattern mining ("this team solved auth this way in project A, and that way in project B") is the killer feature for multi-project engineering orgs.
**Action:** (1) Add pattern clustering (group similar patterns across projects). (2) Add pattern recommendation ("you're about to build auth — here are 3 patterns from your other projects"). (3) Add pattern deprecation tracking (mark patterns as superseded).
**Architecture impact:** Extend `daemon/patterns.py` (~100 LOC). New API endpoints. Dashboard component for pattern browser.

---

## Suggestion: Eval Harness Expansion (Deepen Existing Feature)

**Priority:** P3 (nice-to-have)
**Evidence:** Loom's `daemon/evals.py` (195 lines) is unique in this category — no competitor has an eval harness. Current implementation has basic pass/fail and pass-rate endpoints.
**Rationale:** As the only tool with built-in evaluation, deepening this feature compounds the moat. Eval results become a data flywheel — better evals → better agent recommendations → more agent usage → more data → better evals.
**Action:** (1) Add recall precision@k metrics. (2) Add agent-specific eval suites (different benchmarks for claude-code vs codex). (3) Add temporal eval (does recall accuracy degrade over time as the graph grows?).
**Architecture impact:** Extend `daemon/evals.py` (~80 LOC). New API endpoints for metric queries.

---

## Priority Summary

| Priority | Count | Items |
|----------|-------|-------|
| P0 | 3 | Vector backend persistence, temporal persistence, session persistence |
| P1 | 2 | Managed cloud, multi-modal query planner upgrade |
| P2 | 3 | Framework adapters (AutoGen, CrewAI), production auth, mature SDKs |
| P3 | 2 | Cross-project pattern mining, eval harness expansion |
