# Loom OS — Post-Parity Roadmap (Design Spec)

> Generated 2026-06-29 from `~/.hermes/competitor-analysis/agentic-os/suggestions.md` (2026-06-27 analysis).
> **Scope:** 9 of the 10 post-parity suggestions. Suggestion #8 (Cloud-hosted Loom) is intentionally **dropped** (see "Excluded: #8 Cloud").
> **Status:** Strategy/design only. The task-by-task implementation roadmap is produced separately at `docs/plans/2026-06-29-post-parity-roadmap-implementation.md`.

## 1. Context & Goal

Loom OS has reached **competitive parity** — the previous 12-gap analysis is closed (memory bank, durable task board, hybrid retrieval, sessions, observability, time-travel debugging, MCP, patterns, governance, temporal facts, ingestion). The daemon grew from 7 to 26 modules; the dashboard has a Kanban task board and graph explorer.

The next phase is **not more features for parity** — it is **differentiation and distribution**. This roadmap sequences the 9 remaining suggestions into three priority-tiered phases:

- **Phase 1 (P0):** Close the last feature gaps *and* become discoverable (a feature-complete tool nobody can `pip install` is invisible).
- **Phase 2 (P1):** Expand the addressable market (teams) and remove integration friction (SDK, agent discovery).
- **Phase 3 (P2):** Prove quality (benchmarks) and grow the ecosystem (plugins, framework integrations).

**Guiding constraint:** every item must preserve the competitive moat (Section 6). Anything that would require Docker, Neo4j, an external DB, or breaking the filesystem inbox protocol is rejected or re-scoped — which is exactly why #8 is dropped.

## 2. Current-State Grounding (verified against code)

These facts were verified in the codebase and shape the designs below:

| Area | Current state | Implication |
|------|---------------|-------------|
| `daemon/extractors.py` | `Extractor` ABC (`async extract(text) -> list[ExtractedEntity]`), `ExtractedEntity` (name/kind/confidence/context/relationships), `RegexExtractor`, `ExtractorPipeline` (dedup by `(name,kind)`, **swallows per-extractor exceptions with a warning**). `LLMExtractor` documented as "(future)" but **absent**. | #1 is a clean drop-in; a flaky LLM call cannot break the pipeline. #9 reuses the same ABC as its public plugin contract. |
| `daemon/main.py` CLI | Subcommands: `start`, `register`, `unregister`, `detect-agents`, `worker`. **No `init`.** Entry point `loom = daemon.main:main`. | #3 adds `loom init`. #4 extends `start` host/auth flags. |
| Agent registry | `AgentInfo` model, `AgentRegistry`, `list_agents_by_project`; `register` already accepts `capabilities`. | #6 is **additive** (richer capability schema + directory UI + matching), not greenfield. |
| `pyproject.toml` | `name="loom"`, `version="0.1.0"`, minimal metadata; no classifiers/README/URLs; deps include `graphifyy`, `fastapi`, `aiosqlite`, `pyyaml`. | #3 fills PyPI metadata + version bump. |
| Embeddings + graph | `embeddings.py` (sentence-transformers all-MiniLM-L6-v2, NumPy cosine); Graphify invoked as a **CLI subprocess**, stats read from `graphify-out/graph.json`. | #2's hybrid planner joins these two layers; #7 optimizes the subprocess + parse hot paths. |
| Dashboard | Next.js 16 / React 19, single shared WebSocket, dark theme; components already exist for prior features (eval, patterns, graph, tasks). | Every new feature ships a matching dashboard surface (moat rule). |

## 3. Phasing Overview

| Phase | Features | Theme | Approx. effort |
|-------|----------|-------|----------------|
| **Phase 1 — P0** | #1 LLM Extractor · #2 Relational queries · #3 Ship to users | Feature completion + distribution | ~3-4 weeks |
| **Phase 2 — P1** | #4 Team mode · #5 Client SDK · #6 Agent discovery | Market expansion + DX | ~5-7 weeks |
| **Phase 3 — P2** | #7 Benchmarks · #9 Plugin system · #10 Framework integrations | Quality + ecosystem | ~6-8 weeks |

**Why priority-tiered:** mirrors the source analysis's priority legend exactly and the existing `2026-06-26-competitor-gap-closure-implementation.md` sprint style, minimizing reinterpretation. Within each phase, items are ordered by data-flow dependency (Section 5), not just priority.

## 4. Per-Feature Design

Each feature lists: **Goal**, **Key files**, **Architecture approach**, **Dashboard deliverable**, **Effort**, **Dependencies/risks**. Detail at the task level lives in the implementation plan.

### Phase 1 — P0 (Differentiators)

#### #1 — Production-ready LLM Extractor
- **Goal:** Match Cognee/Graphiti's LLM-powered extraction quality while keeping `RegexExtractor` as the zero-dependency always-on fallback.
- **Key files:** modify `daemon/extractors.py`; new `tests/test_extractors.py` cases; dashboard edge-style update.
- **Architecture:** Implement `LLMExtractor(Extractor)` honoring the existing `async extract(text) -> list[ExtractedEntity]` contract. Configurable backend resolved at init: **Ollama (default, local)** → OpenAI → Claude, selected via env/config. Graphiti-style two-pass prompt (entities, then edges) returning structured JSON mapped to `ExtractedEntity` with real per-entity `confidence`. Register in `ExtractorPipeline` *after* `RegexExtractor` so regex wins ties on dedup; the pipeline's existing exception-swallowing means a backend outage degrades gracefully to regex-only.
- **Dashboard:** render auto-extracted (LLM) edges with the already-designed dashed style; show confidence on hover.
- **Effort:** 3-5 days.
- **Dependencies/risks:** new *optional* deps (`openai`/`anthropic`/Ollama HTTP client) — must stay optional so the base install is unchanged. Prompt-injection from finding text into the LLM call is an accepted low risk (local, single-user).

#### #2 — Relational query support (graph + vector + relational)
- **Goal:** Cognee's marquee multi-modal retrieval — joins across graph traversal and vector similarity in one query — plus code-specific AST context Cognee lacks.
- **Key files:** modify `daemon/graph_engine.py` (query planner), `daemon/api.py` (query mode), `daemon/embeddings.py` (seed integration); dashboard search.
- **Architecture:** Introduce a `relation` edge type linking findings ↔ code entities and embeddings ↔ graph nodes. Add a `hybrid` query mode: vector similarity selects seed nodes, then graph BFS expands along `relation`/dependency edges, supporting JOIN-style queries ("entities semantically near X that also depend on Y"). Results carry **both** a structural relevance (graph path/distance) and a semantic relevance (cosine score).
- **Dashboard:** "hybrid" toggle on the existing search bar; results show dual relevance (path + score).
- **Effort:** 1-2 weeks.
- **Dependencies/risks:** consumes #1's enriched edges, so it should land after #1. Risk: graph.json schema changes must not break Graphify's own output (covered by the moat checklist verification).

#### #3 — Ship to users (PyPI, docs, quickstart)
- **Goal:** Make Loom installable and discoverable. Distribution is the actual gap vs. competitors, not features.
- **Key files:** `pyproject.toml` metadata; `daemon/main.py` (`loom init`); `README.md` rewrite; optional `mkdocs.yml` + `docs/site/`.
- **Architecture:** Fill `pyproject.toml` (description, classifiers, README `readme=`, project URLs, `keywords`, version bump to a real release number) and publish to PyPI. Add a `loom init` subcommand that bootstraps a project (creates `~/.loom` scaffolding, registers the current dir, prints next steps). Write a quickstart (install → `loom start` → register agent → open dashboard) as a comprehensive README plus optional docs site.
- **Dashboard:** none required; optionally a first-run/empty-state pointer to the quickstart.
- **Effort:** 1-2 weeks (mostly docs + packaging polish).
- **Dependencies/risks:** README is currently partly stale (claims things are out-of-scope that already shipped) — the rewrite must reflect real capabilities. Naming drift (product "Loom OS", package "loom", repo "agentic-os") should be stated once, clearly, in the README.

### Phase 2 — P1 (High Upside)

#### #4 — Team mode (shared daemon, multi-user)
- **Goal:** Expand from solo to teams without abandoning local-first.
- **Key files:** `daemon/api.py` (auth middleware), `daemon/main.py` (`start` flags), `daemon/registry.py` (per-user schema), `watcher.py`/`router.py` (per-user inbox paths); dashboard team view + auth.
- **Architecture:** Support `--host 0.0.0.0` with **optional** API-key/token auth middleware (off by default — local single-process is unchanged). Multi-user isolation via per-user inbox subdirectories `~/.loom/inbox/<project>/<user>/`; `SHARED_CONTEXT.md` aggregates cross-user findings. Optional WebSocket auth for remote dashboard connections.
- **Dashboard:** team view showing all agents across all users; auth entry when enabled.
- **Effort:** 2-3 weeks.
- **Dependencies/risks:** auth must be strictly opt-in so the moat (no-auth inbox, single-process default) is preserved. Shared filesystem (NFS/Syncthing) is the deployment assumption — documented, not built.

#### #5 — Client SDK (`loom-client`)
- **Goal:** Remove the last friction in the inbox protocol — agents writing raw JSON/markdown by hand.
- **Key files:** new `loom-client/` Python package (separate from daemon); npm twin; examples.
- **Architecture:** Thin wrappers over file writes with Pydantic validation: `register / heartbeat / finding / task` one-liners that write to the correct inbox paths in the correct schema. JS/TS npm package mirrors the API. Ships examples for Claude Code, shell, and Python agents. **No daemon changes** — the SDK is purely additive and the raw-file path stays fully supported (moat).
- **Dashboard:** none.
- **Effort:** 1-2 weeks.
- **Dependencies/risks:** must track the inbox schema in `daemon/models.py` (single source of truth) to avoid drift; pairs naturally with #3 packaging.

#### #6 — Agent discovery / directory
- **Goal:** Multi-agent coordination — agents and humans can see who else is on a project and what they can do.
- **Key files:** `daemon/models.py` (capability schema), `daemon/api.py` (`GET /api/projects/{id}/agents`), `daemon/registry.py`; dashboard directory view.
- **Architecture:** Enrich the existing agent capability data into a structured schema `{name, description, tools, models, status}`. Expose a capability-listing endpoint (registry already stores the data). Add cross-agent capability matching ("needs a reviewer → agent Y has review capability").
- **Dashboard:** "Agent Directory" view — all registered agents, capabilities, recent activity.
- **Effort:** 1-2 weeks.
- **Dependencies/risks:** mostly additive over the existing registry; low risk.

### Phase 3 — P2 (Future Advantage)

#### #7 — Performance benchmarks & optimization
- **Goal:** Prove the single-process/SQLite/NumPy architecture is faster than Cognee's Docker+Neo4j, and make it marketing-grade.
- **Key files:** new `benchmarks/` harness; targeted optimization in `graph_engine.py` (subprocess invocation, graph.json parse caching), `embeddings.py` (async batching).
- **Architecture:** Harness ingests a large codebase, then measures recall precision, query latency, and graph build time; compares against Cognee/Graphiti on equivalent tasks. Optimization passes target the measured hot paths (likely the Graphify subprocess round-trip and repeated graph.json parsing).
- **Dashboard:** optional benchmark/metrics surface; publish a comparison page.
- **Effort:** 2-3 weeks.
- **Dependencies/risks:** benchmarks should run after #1/#2 land so they measure the real retrieval stack. Caching must not serve stale graph data.

#### #9 — Plugin system for extractors & ingestors
- **Goal:** Let the community contribute language/framework-specific extractors — multiplying value without core changes.
- **Key files:** `daemon/extractors.py` (public contract), daemon startup (plugin loader); `~/.loom/plugins/extractors/`.
- **Architecture:** Promote the existing `Extractor` ABC to a documented public plugin contract. Daemon scans `~/.loom/plugins/extractors/<name>.py` on startup, each exposing a standard `register()` hook, and adds them to `ExtractorPipeline`. Ship 2-3 example plugins (Python patterns, Git history, TODO scanner).
- **Dashboard:** list discovered plugins + enable/disable.
- **Effort:** 2-3 weeks.
- **Dependencies/risks:** third-party plugin code runs in-process — document the trust boundary (local plugins only; no remote auto-install in v1). Builds directly on #1's pipeline maturity.

#### #10 — LangChain / LlamaIndex / CrewAI integrations
- **Goal:** Discoverability in the largest agent ecosystem (most agents find memory tools via "LangChain memory").
- **Key files:** new packages `langchain-loom`, `llama-index-loom`, `crewai-loom` (separate from daemon).
- **Architecture:** Thin wrappers over the inbox protocol / REST API (and ideally over #5's SDK). `langchain-loom` implements LangChain's `BaseMemory`; `llama-index-loom` a storage backend; `crewai-loom` shared crew memory. **No daemon changes.**
- **Dashboard:** none.
- **Effort:** 2-3 weeks (~1 week per integration).
- **Dependencies/risks:** should land after #5 so the integrations wrap the SDK rather than re-implementing file I/O three times.

## 5. Cross-Cutting Concerns

**Intra-/inter-phase ordering (data-flow, not just priority):**
- #1 → #2: #1 enriches the graph with LLM-extracted, confidence-scored edges that #2's hybrid planner traverses. Land #1 first so #2 demos against real data.
- #3 ↔ #5: packaging and the client SDK are one distribution story; #5 reuses #3's release pipeline.
- #5 → #10: the framework integrations wrap the SDK, so #5 precedes #10.
- #1 → #9: the plugin system generalizes the now-mature extractor pipeline.
- #1/#2 → #7: benchmarks measure the completed retrieval stack.

**Testing strategy:** every new daemon module gets `tests/test_<module>.py`; the existing suite must stay green at the end of every phase; new WebSocket events are emitted for every new state change (no silent state). Separate packages (#5, #10) carry their own tests.

**Definition of done per phase:**
- **Phase 1:** `pip install loom-os` works from PyPI; `loom init` bootstraps a project; LLM extraction produces confidence-scored edges (degrading to regex when no backend); hybrid query returns dual-relevance (path + cosine) results.
- **Phase 2:** daemon runs multi-user behind optional auth with per-user inbox isolation; `loom-client` (py + npm) published with examples; Agent Directory lists capabilities and supports matching.
- **Phase 3:** published benchmark comparison vs. Cognee/Graphiti; at least 2 example extractor plugins auto-discovered; one framework integration (LangChain) published.

## 6. Competitive Moat — Guardrails (Non-Negotiable)

Carried into every task; any change that violates these is rejected or re-scoped:

| Moat | Guard |
|------|-------|
| Filesystem inbox protocol | Extend it (#5 wraps it, #4 sub-paths it) — never replace it with a required SDK or auth gate. |
| Single-process daemon | `pip install` + `loom start` stays the only run path. No Docker/Neo4j/external DB/cloud service. |
| Per-project isolation | All new features scoped to project boundaries (and, for #4, to per-user sub-scopes). |
| Code-specific Graphify AST | LLM extraction (#1) and hybrid queries (#2) **enrich** the graph; they never replace AST-level understanding. |
| Dashboard control plane | Every user-facing feature ships a dashboard surface. |
| WebSocket live updates | Push, not poll — new events for all new state changes. |
| MCP + inbox dual path | Both integration paths stay maintained; #5/#10 add to, not replace, them. |

## 7. Excluded: #8 Cloud-Hosted Loom

**Dropped from this roadmap.** Rationale:
- It directly contradicts the moat ("single-process daemon — don't add Docker, Neo4j, or external infrastructure").
- #4 (Team mode) already delivers the bulk of the multi-user value (shared daemon, multi-user isolation, cross-user findings) without multi-tenant infra, billing, or managed hosting.
- Removing it keeps the roadmap focused on the local-first identity that is Loom's differentiator.

If managed hosting is ever revisited, it should be a separate initiative with its own spec, explicitly gated on real team demand — not folded into this roadmap.

## 8. Next Steps

1. Review and approve this spec.
2. Generate the task-level implementation roadmap (`docs/plans/2026-06-29-post-parity-roadmap-implementation.md`) via the writing-plans skill: per-feature task breakdowns, files, sequencing, and verification, ordered by the Section 5 data-flow.
3. Implement Phase 1 first (it is the launch-enabling phase); re-run competitor analysis at the start of Phase 3 (the category moves fast).
