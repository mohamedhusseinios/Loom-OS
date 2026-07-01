# Loom OS "Next Moat" Roadmap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Source analysis:** `.hermes/competitor-analysis/loom-os/suggestions.md` + `.hermes/competitor-analysis/loom-os/plan-inputs.md` (both generated 2026-07-01).
> **Predecessor:** [docs/plans/2026-06-29-post-parity-roadmap-implementation.md](2026-06-29-post-parity-roadmap-implementation.md) shipped all 9 gap-closure features. Its Phase 3 note said "re-run the competitor analysis before proceeding" — that re-analysis produced *this* plan.
> **Detail policy:** **Phase 1 (P0) is fully task-by-task / test-first** because it is the next work to execute. **Phases 2–4 are architecture-level outlines** — expand each feature into its own detailed plan under `docs/plans/` when that phase begins.

**Goal:** Convert Loom's feature lead (30/31 dimensions vs the next competitor's 9) into a durable, defensible moat by shipping distribution assets (published benchmarks, docs, community), hardening first-generation modules, and adding category-defining capabilities (cross-project federation) — without breaking Loom's local-first, single-process, filesystem-protocol moat.

**Architecture:** Extend the existing Python FastAPI daemon (`daemon/`) and Next.js dashboard (`dashboard/`). Distribution work (benchmarks, docs) ships as repo artifacts and a separate static docs site — **zero daemon changes**. Maturity + federation work adds new modules and defensive guards inside the single daemon process. Framework integrations ship as **separate optional packages** under `integrations/` that delegate to `loom-client`. Graphify stays the AST source of truth; nothing here dilutes that.

**Tech Stack:** Python 3.11+ (FastAPI, uvicorn, aiosqlite, watchdog, numpy, sentence-transformers, pyyaml, graphify), TypeScript (Next.js 16, React 19, shadcn, Cytoscape), MkDocs Material (docs site), MCP (stdio). LLM backends optional: Ollama (default/local), OpenAI, Anthropic.

## Global Constraints

Copied verbatim from the predecessor roadmap's spec and the fresh analysis's Differentiation Strategy — **every task implicitly includes these. They are the moat; do not regress them.**

- **Single-process daemon** — `loom start` stays the only run command for the default install. No Docker, Neo4j, external DB, or cloud service is *required*. (Phase 3's cloud decision may add an *optional* deployment artifact — see the explicit gate in Feature #6; it never becomes the default path.)
- **Filesystem inbox protocol preserved** — extend it; never replace it with a required SDK or auth gate. The raw-file path stays fully supported.
- **Per-project isolation intact** — federation (Feature #5) is **read-only across projects**; no project may write to another's graph.
- **Code-specific Graphify AST not diluted** — incremental persistence and federation **enrich**, never replace, AST understanding.
- **Every user-facing feature ships a dashboard surface** where one applies (federation gets `federation-explorer.tsx`; benchmarks/docs are external artifacts and are exempt).
- **WebSocket stays push-not-poll** — emit new events for every new state change.
- **New optional dependencies must stay optional** — the base `pip install loom-os` install must not require an LLM client, MkDocs, or any competitor's stack.
- **Existing test suite must stay green at the end of every phase**; every new daemon module gets `tests/test_<module>.py`.

### Operational gotcha (applies to every daemon-code task in Phases 2–4)

The daemon serves **in-memory code**. After editing any `daemon/*.py`, **restart the daemon** before manual verification — a stale process produces phantom "missing feature"/404 bugs (the tell: a default `{"detail":"Not Found"}` body instead of a custom 404). This is a recorded, recurring failure mode in this repo. See the daemon-patterns section of `CLAUDE.md`.

### Test-mode reminder (applies to any new API route)

`api.py` uses module-global singletons (`registry`, `graph_engine`, `router`, …), not DI. `lifespan` checks `registry is not None` to detect **test mode** and skips the watcher/broadcast task. Tests assign `api_module.registry = <temp-backed AgentRegistry>` before constructing `TestClient`. Follow this pattern for any new tested route — see `tests/test_api.py`.

---

# PHASE 1 — P0: Distribution & Community — DETAILED

> **Framing:** The product is feature-complete; **discoverability is the binding constraint.** These two features are primarily execution + light hardening, not new subsystems.
> **Recommended order (from plan-inputs Open Question #2):** benchmarks first (≈2h, higher leverage, harness exists), then docs (≈2 days).

## Feature #1 — Publish Reproducible Benchmarks (Suggestion 1)

**Why:** The eval harness (`daemon/evals.py`) and benchmark runner (`benchmarks/`) exist but have **never run head-to-head** against Cognee/Graphiti. No competitor has published comparison data — being first is a marketing moat. Loom's single-process/SQLite/NumPy architecture *should* win on setup time, latency, and resource use.

**The real gap (verified in current code):** `benchmarks/harness.py` emits **Loom-only** numbers, and `benchmarks/report.py` **hardcodes competitor estimates** (`~200-500ms*`). Publishing fabricated estimates is not credible. The minimal-but-necessary code work below makes results **self-describing and reproducible**, and makes the comparison table render **only real, measured numbers** (or an explicit "not measured"), never invented ones.

> If you truly want *zero* code (per the analysis's "no new code" claim), skip Tasks 1.1–1.2, run the existing harness, and hand-write `BENCHMARKS.md`. The tasks below exist because "reproducible" and "credible" are the whole point of the suggestion, and the current report undermines both.

### Task 1.1: Make benchmark results self-describing and reproducible

**Files:**
- Modify: `benchmarks/harness.py`
- Test: `tests/test_benchmarks.py` (create)

**Interfaces:**
- Consumes: `GraphEngine.build_project(repo_path) -> BuildResult`, `GraphEngine.get_stats(repo_path) -> Stats` (has `.nodes`, `.edges`, `.communities`), `GraphEngine.hybrid_query(repo_path, agent, query)` — all already in `daemon/graph_engine.py`.
- Produces: a pure, sync helper `shape_metrics(system: str, repo_sha: str, build_time_s: float, stats, latencies_ms: list[float]) -> dict` returning keys `system, repo_sha, build_time_s, nodes, edges, communities, avg_query_latency_ms, queries_run`. `run(repo_path, system="loom-os")` calls it so `run()` stays thin and the shaping logic is unit-testable without a live Graphify build.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmarks.py
"""Tests for the benchmark harness metric-shaping and report rendering."""
from types import SimpleNamespace

from benchmarks.harness import shape_metrics


def test_shape_metrics_is_self_describing():
    stats = SimpleNamespace(nodes=536, edges=4050, communities=12)
    m = shape_metrics(
        system="loom-os",
        repo_sha="80fa21a",
        build_time_s=1.234,
        stats=stats,
        latencies_ms=[10.0, 20.0, 30.0],
    )
    assert m["system"] == "loom-os"
    assert m["repo_sha"] == "80fa21a"
    assert m["build_time_s"] == 1.23          # rounded to 2dp
    assert m["nodes"] == 536
    assert m["edges"] == 4050
    assert m["communities"] == 12
    assert m["avg_query_latency_ms"] == 20.0  # mean of 10/20/30
    assert m["queries_run"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_benchmarks.py::test_shape_metrics_is_self_describing -v`
Expected: FAIL with `ImportError: cannot import name 'shape_metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
# benchmarks/harness.py — add above run(); refactor run() to use it.
def shape_metrics(system, repo_sha, build_time_s, stats, latencies_ms):
    """Shape raw benchmark measurements into a self-describing metrics dict."""
    avg = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0
    return {
        "system": system,
        "repo_sha": repo_sha,
        "build_time_s": round(build_time_s, 2),
        "nodes": stats.nodes,
        "edges": stats.edges,
        "communities": stats.communities,
        "avg_query_latency_ms": round(avg, 1),
        "queries_run": len(latencies_ms),
    }
```

```python
# benchmarks/harness.py — rewrite run() to capture the target's git SHA and delegate shaping.
import subprocess

async def run(repo_path: str, system: str = "loom-os") -> dict:
    """Run benchmarks against a repo. Returns a self-describing metrics dict."""
    from daemon.graph_engine import GraphEngine

    engine = GraphEngine()

    t0 = time.monotonic()
    await engine.build_project(repo_path)
    build_time = time.monotonic() - t0

    stats = await engine.get_stats(repo_path)

    queries = ["authentication", "database", "error handling", "main entry point"]
    latencies = []
    for q in queries:
        t0 = time.monotonic()
        await engine.hybrid_query(repo_path, "bench", q)
        latencies.append((time.monotonic() - t0) * 1000)

    try:
        repo_sha = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:
        repo_sha = "unknown"

    return shape_metrics(system, repo_sha, build_time, stats, latencies)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_benchmarks.py::test_shape_metrics_is_self_describing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchmarks/harness.py tests/test_benchmarks.py
git commit -m "feat(bench): self-describing, reproducible benchmark metrics (system + repo_sha)"
```

### Task 1.2: Render an honest multi-system comparison (no fabricated estimates)

**Files:**
- Modify: `benchmarks/report.py`
- Test: `tests/test_benchmarks.py`

**Interfaces:**
- Consumes: metrics dicts shaped by `shape_metrics` (Task 1.1).
- Produces: `generate_report(systems: list[dict], output_path="BENCHMARKS.md") -> str`. Renders one comparison row per measured system. A system dict may set `"not_measured": True` (with only `system`) → its cells render `not measured` rather than a number. **No hardcoded competitor numbers.**

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_benchmarks.py
from benchmarks.report import generate_report


def test_report_renders_only_measured_numbers(tmp_path):
    loom = {
        "system": "loom-os", "repo_sha": "80fa21a", "build_time_s": 1.2,
        "nodes": 536, "edges": 4050, "communities": 12,
        "avg_query_latency_ms": 18.4, "queries_run": 4,
    }
    cognee = {"system": "cognee", "not_measured": True}
    out = tmp_path / "BENCHMARKS.md"
    md = generate_report([loom, cognee], output_path=str(out))

    assert "loom-os" in md and "cognee" in md
    assert "18.4" in md                 # real measured latency present
    assert "not measured" in md         # competitor not fabricated
    assert "200-500ms" not in md        # old hardcoded estimate is gone
    assert out.read_text() == md        # written to disk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_benchmarks.py::test_report_renders_only_measured_numbers -v`
Expected: FAIL — current `generate_report(metrics: dict, ...)` takes a single dict and contains `200-500ms`.

- [ ] **Step 3: Write minimal implementation**

```python
# benchmarks/report.py — replace generate_report with a multi-system, estimate-free version.
from pathlib import Path

_HEADER = """# Loom OS Benchmarks

> Reproducible head-to-head measurements. Every number below was measured on the
> same task and repo commit. Cells marked **not measured** were not run — Loom does
> not publish estimated competitor numbers. See `benchmarks/README.md` to reproduce.

## Why Loom is structurally fast

- Single-process daemon — no Docker, no Neo4j, no network round-trips.
- `graph.json` mtime cache — zero repeated JSON parsing.
- NumPy cosine similarity — O(n), no index overhead below ~10K docs.

## Results
"""

def _cell(sys_metrics, key, suffix=""):
    if sys_metrics.get("not_measured"):
        return "not measured"
    val = sys_metrics.get(key)
    return f"{val:,}{suffix}" if isinstance(val, int) else f"{val}{suffix}"

def generate_report(systems: list[dict], output_path: str = "BENCHMARKS.md") -> str:
    """Render an honest comparison table from measured metrics only."""
    rows = ["| System | Repo @ | Build time | Nodes | Edges | Avg query latency |",
            "|--------|--------|-----------|-------|-------|-------------------|"]
    for s in systems:
        sha = s.get("repo_sha", "—") if not s.get("not_measured") else "—"
        rows.append(
            f"| {s['system']} | {sha} | {_cell(s, 'build_time_s', 's')} | "
            f"{_cell(s, 'nodes')} | {_cell(s, 'edges')} | "
            f"{_cell(s, 'avg_query_latency_ms', 'ms')} |"
        )
    md = _HEADER + "\n" + "\n".join(rows) + "\n"
    Path(output_path).write_text(md)
    return md
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_benchmarks.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add benchmarks/report.py tests/test_benchmarks.py
git commit -m "feat(bench): honest multi-system comparison report — no fabricated estimates"
```

### Task 1.3: Document the reproducible competitor setup

**Files:**
- Create: `benchmarks/README.md`

**Not test-driven — this is a documentation/execution deliverable.** Acceptance = a reader can reproduce every number.

- [ ] **Step 1: Write `benchmarks/README.md`** containing, verbatim and runnable:
  1. **Loom run:** `python -m benchmarks.harness <repo_path> > benchmarks/loom.json` (note: needs `.venv` active and `graphify` on PATH).
  2. **Reference corpus:** pin ONE public repo at ONE commit for all systems (e.g. `git clone <url> && git -C <url> checkout <sha>`); record the SHA. Every system must ingest the *same* tree.
  3. **Cognee:** exact `docker compose` snippet to bring up Neo4j + PGVector, the ingest call, and how to time build + query to emit a metrics JSON matching the Task 1.1 schema (`system: "cognee"`, same keys).
  4. **Graphiti:** equivalent Neo4j bring-up + ingest + timing snippet emitting the same schema.
  5. **Combine + render:** `python -c "from benchmarks.report import generate_report, json; ..."` reading `loom.json`, `cognee.json`, `graphiti.json` (use `{"system": "...", "not_measured": true}` for any system you could not stand up) → writes root `BENCHMARKS.md`.
  6. **Hardware note:** record CPU/RAM/OS so numbers are interpretable.

- [ ] **Step 2: Commit**

```bash
git add benchmarks/README.md
git commit -m "docs(bench): reproducible competitor setup + run instructions"
```

### Task 1.4: Run the head-to-head and publish `BENCHMARKS.md`

**Files:**
- Create: `BENCHMARKS.md` (generated), Modify: `README.md` (link it)

**Execution task.** If a competitor stack cannot be stood up in your environment, pass it as `{"system": "...", "not_measured": true}` — an honest partial table beats a fabricated full one.

- [ ] **Step 1:** Activate `.venv`; run Loom on the pinned corpus → `benchmarks/loom.json`.
- [ ] **Step 2:** Follow `benchmarks/README.md` for Cognee and Graphiti (or mark not-measured).
- [ ] **Step 3:** Render the combined report to the repo root:

```bash
python -c "import json; from benchmarks.report import generate_report; \
generate_report([json.load(open('benchmarks/loom.json')), \
{'system':'cognee','not_measured':True}, \
{'system':'graphiti','not_measured':True}])"
```

- [ ] **Step 4:** Add a **Benchmarks** section to `README.md` linking `BENCHMARKS.md`.
- [ ] **Step 5: Commit**

```bash
git add BENCHMARKS.md README.md
git commit -m "docs: publish reproducible head-to-head benchmarks"
```

---

## Feature #2 — Documentation Site + Community Channel (Suggestion 2)

**Why:** 31 feature dimensions, 24 daemon modules, a dashboard, two SDKs, an MCP server, and a LangChain integration — with **no docs site and no community channel.** A developer landing on the repo sees 24 Python modules and bounces. Discoverability is now the bottleneck.

**Framework decision (made here so the plan is concrete):** **MkDocs Material.** Rationale: the daemon is Python, so `pip install mkdocs-material` fits the toolchain; the site is a single `mkdocs.yml` + Markdown (trivial CI, GitHub-Pages deploy, no Node build); and it stays a *separate optional dependency*. (Fumadocs/Next.js is the natural alternative if you want the site to share the dashboard's component system — swap Tasks 2.1/2.3 accordingly.)

### Task 2.1: Scaffold the MkDocs Material site

**Files:**
- Create: `mkdocs.yml`, `docs-site/index.md`, `docs-site/requirements.txt`

- [ ] **Step 1:** Create `docs-site/requirements.txt`:

```
mkdocs-material>=9.5
```

- [ ] **Step 2:** Create `mkdocs.yml`:

```yaml
site_name: Loom OS
site_description: Unified agent memory fabric for multi-agent coding
docs_dir: docs-site
theme:
  name: material
  palette:
    scheme: slate
  features:
    - navigation.sections
    - content.code.copy
nav:
  - Home: index.md
  - Quickstart: quickstart.md
  - Concepts:
      - Filesystem protocol: concepts/filesystem-protocol.md
      - Knowledge graph: concepts/knowledge-graph.md
  - Guides:
      - Connect Claude Code: guides/connect-claude-code.md
      - Custom extractor plugin: guides/custom-extractor-plugin.md
      - Hybrid search: guides/hybrid-search.md
  - Reference:
      - CLI: reference/cli.md
      - API: reference/api.md
```

- [ ] **Step 3:** Create `docs-site/index.md` — a one-screen "what is Loom OS" (pull the one-liner + the two-process split from `CLAUDE.md`; link Quickstart).
- [ ] **Step 4: Verify the site builds (this is the docs "test"):**

Run: `pip install -r docs-site/requirements.txt && mkdocs build --strict`
Expected: exit 0, `site/` produced, **no broken-link or missing-nav warnings** (`--strict` fails on any).

- [ ] **Step 5: Commit**

```bash
git add mkdocs.yml docs-site/index.md docs-site/requirements.txt
git commit -m "docs(site): scaffold MkDocs Material site"
```

### Task 2.2: Write the core pages

**Files:** Create the eight pages listed in `mkdocs.yml` nav.

Each page must contain **real commands**, not prose placeholders. Minimum concrete content per page:

- [ ] `quickstart.md` — the 5-minute path, verbatim commands: `python -m venv .venv && source .venv/bin/activate`, `pip install loom-os`, `loom --port 8472`, drop a `register.json` into `~/.loom/inbox/<project>/`, `cd dashboard && npm install && npm run dev`, open `http://localhost:3000`.
- [ ] `concepts/filesystem-protocol.md` — the inbox file table (`register.json`, `heartbeat.json`, `finding-*.md`, `decision-*.md`, `task-*.json`) and the `.processed/` move, copied from `CLAUDE.md`.
- [ ] `concepts/knowledge-graph.md` — Graphify-as-subprocess, `graphify-out/graph.json`, AST source-of-truth + LLM-extracted sidecar edges.
- [ ] `guides/connect-claude-code.md` — register an agent via `loom-client` (Python) and via a raw `register.json`; heartbeat loop.
- [ ] `guides/custom-extractor-plugin.md` — the `Extractor` ABC contract, drop into `~/.loom/plugins/extractors/<name>.py`, auto-discovery (points at Feature #9 examples).
- [ ] `guides/hybrid-search.md` — `GraphEngine.hybrid_query`, the dashboard toggle, what graph+vector+relational returns.
- [ ] `reference/cli.md` — `loom`, `loom worker`, `loom init` flags (from `CLAUDE.md` Commands).
- [ ] `reference/api.md` — link/embed the existing API reference in `docs/`.
- [ ] **Verify + commit:**

Run: `mkdocs build --strict`
Expected: exit 0, no warnings.

```bash
git add docs-site/
git commit -m "docs(site): quickstart, concepts, guides, reference pages"
```

### Task 2.3: CI build + GitHub Pages deploy

**Files:** Create `.github/workflows/docs.yml`

- [ ] **Step 1:** Add a workflow that (a) on PR: `pip install -r docs-site/requirements.txt && mkdocs build --strict`; (b) on push to `main`: `mkdocs gh-deploy --force`.
- [ ] **Step 2:** Verify the YAML parses (`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docs.yml'))"` → exit 0).
- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): build docs on PR, deploy to Pages on main"
```

### Task 2.4: Open a community channel

**Files:** Create `CONTRIBUTING.md`; Modify `README.md`

- [ ] **Step 1:** Enable **GitHub Discussions** in repo settings (manual, zero-infra) — document that this was done.
- [ ] **Step 2:** Write `CONTRIBUTING.md` (how to run the daemon + dashboard, run `pytest tests/`, the daemon-restart gotcha, where plans live).
- [ ] **Step 3:** Add **Docs**, **Discussions**, and (optional) **Discord** links to the top of `README.md`.
- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md README.md
git commit -m "docs: add CONTRIBUTING + community links (Discussions)"
```

**Phase 1 exit criteria:** `pytest tests/` green; `mkdocs build --strict` exit 0; root `BENCHMARKS.md` exists with a populated comparison table + reproduction steps; README links both.

---

# PHASE 2 — P1: Maturity Hardening — OUTLINE

> **Expand each feature below into its own detailed `docs/plans/<date>-<name>.md` (test-first) when this phase begins.** The `plan-inputs.md` "Architecture Implications" section already contains per-file, per-method specifics — use it as the spec for each expansion.
> **Recommended order (plan-inputs):** #3 (highest technical leverage — prevents a scaling wall) → #4 (start with `temporal.py`) → #5 (category-defining).

## Feature #3 — Incremental Graph Persistence

- **Goal:** Replace full-source Graphify rebuilds with change-scoped merges so large monorepos / many projects don't hit the `MIN_UPDATE_INTERVAL` (1 update / 30s / project) wall in `router.py`.
- **Files:** Modify `daemon/graph_engine.py` (~100–150 LOC: add `async incremental_update(self, project_path: str, changed_files: set[str]) -> None` beside `_run_graphify_build`, reusing the read path for cached graph state), `daemon/watcher.py` (~20 LOC: pass the changed-files set instead of the bare project path), `daemon/router.py` (~10 LOC: thread the changed-files set through the graph-update scheduler). Test: `tests/test_graph_engine.py` (~80 LOC).
- **Test focus:** incremental add doesn't drop existing nodes; modifying one file replaces only its node's edges (siblings untouched); deleting a file removes only its nodes.
- **Hard constraint:** an incremental merge must produce results **equivalent to a full rebuild** for the changed subset — Graphify's `graph.json` contract must never be corrupted.
- **Effort:** ~1 week. **Expand into:** `docs/plans/<date>-incremental-graph-persistence-implementation.md`.

## Feature #4 — Mature the Five First-Generation Modules

- **Goal:** Move `temporal / traces / sessions / snapshots / patterns` from "present" to "battle-tested" before any public claim about temporal tracking or tracing. Each is <210 LOC today.
- **Pattern per module:** targeted edge-case tests + `asyncio.Lock` around state mutations + defensive error handling. Extend the **existing** `tests/test_<module>.py` (no new test files). ~250 LOC code + ~210 LOC tests total.

| Module | LOC → target | Concrete hardening (from plan-inputs) |
|--------|-------------|----------------------------------------|
| `temporal.py` | 152 → ~220 | Lock `record()`/`expire()`; boundary tests at exactly `valid_from`/`valid_to`; expired-with-no-`valid_to` case |
| `traces.py` | 159 → ~210 | Idempotent `finish_span()`; eviction boundary (`max_spans` = 0, 1); 100 concurrent `start_span` never exceeds max |
| `sessions.py` | 128 → ~180 | try/except in `_bridge_to_inbox()` for mailbox write failures; context survives restart; `end_session()` cleanup |
| `snapshots.py` | 126 → ~180 | Guard `replay()` against partial/corrupt snapshots; `capture()`+`replay()` roundtrip; eviction keeps most-recent N |
| `patterns.py` | 209 → ~270 | Expand `_normalise()` (stemming, abbreviations); `cross_project_patterns()` dedup; `deprecate()` status transition |

- **Order decision (plan-inputs Open Question #3):** start with `temporal.py` for the strongest "we match Graphiti" claim, **or** `patterns.py` for the strongest unique-value (cross-project) claim. **Pick one before starting.**
- **Effort:** ~1–2 weeks. **Expand into:** `docs/plans/<date>-module-maturity-hardening-implementation.md`.

## Feature #5 — Cross-Project Graph Federation

- **Goal:** A read-only index across all `~/.loom/inbox/*/graphify-out/graph.json` so users can ask "which projects use pattern/symbol X?" — a capability **no competitor is positioned to deliver** (they use flat namespaces).
- **Files:** Create `daemon/federation.py` (~120 LOC: `FederatedIndex` with `build_index()`, `query(question, depth=2)`, `cross_project_references(symbol)`), Modify `daemon/api.py` (+~30 LOC: `GET /api/federated-query?q=&depth=`, `GET /api/federated/references?symbol=`), Create `dashboard/components/federation-explorer.tsx` (~150 LOC), Test `tests/test_federation.py` (~60 LOC).
- **Test focus:** two projects sharing a node both appear in a federated query; `cross_project_references` finds a symbol across repos.
- **Hard constraint:** **read-only** across projects — preserves per-project isolation; no cross-writes.
- **Open question (plan-inputs #4):** for team mode, is federation **per-user** or **organization-wide**? This decides the index scope — resolve before building.
- **Effort:** ~1–1.5 weeks. **Expand into:** `docs/plans/<date>-cross-project-federation-implementation.md`.

---

# PHASE 3 — P2: Go-To-Market Positioning — OUTLINE

## Feature #6 — Cloud / Hosted Offering **Decision** (strategic gate)

> **This is a business decision, not a coding task, and it is the one place that touches the "single-process / no-Docker" moat constraint. Resolve it explicitly before any cloud-related work begins.** Do not let it be decided by silence.

- **Evidence:** every competitor >20K stars has a hosted option (Cognee/Zep/Mem0/Letta/LangGraph Cloud). Loom has none.
- **Option A — ship managed:** `Dockerfile` (~20 LOC) + `docker-compose.yml` (~30 LOC) for the single-process daemon; multi-tenant isolation via the existing team-mode per-user inbox scoping; **optional** Postgres backend in `registry.py` (~100 LOC behind a connection-string check). The Docker artifact is an *optional deployment path*, never the default `pip install`.
- **Option B — self-hosted-by-design positioning:** a position paper ("your agent memory never leaves your machine"). Zero code.
- **Deliverable of this feature:** a written, committed decision (an ADR under `docs/` or `docs/adr/`). Only if Option A is chosen does it spawn `docs/plans/<date>-loom-cloud-implementation.md`.
- **Effort:** decision now; ~1–2 weeks if Option A.

## Feature #7 — MCP Ecosystem Positioning

- **Goal:** Position Loom as "the richest MCP-compatible memory backend" — a cheap distribution channel into every MCP client (Claude Code, Cursor, Windsurf).
- **Files:** Modify `daemon/mcp_server.py` (+~60 LOC): add `discover_agents(project)` (wraps `registry.list_agents_by_project()`), `query_temporal_facts(project, timestamp=None)` (wraps `TemporalTracker.active_facts()`/`.facts_at()`), `search_patterns(project, query)` (wraps `PatternRepository.list_patterns()`). All **read-only**, no new infra. Test `tests/test_mcp.py` (+~30 LOC).
- **Effort:** ~2–3 days. **Expand into:** `docs/plans/<date>-mcp-ecosystem-tools-implementation.md`.

---

# PHASE 4 — P3: Ecosystem Expansion — OUTLINE

## Feature #8 — LlamaIndex + CrewAI Integrations

- **Goal:** Replicate the proven `langchain-loom` pattern (commit `d13667c`) into two more ecosystems for discoverability.
- **Files:** Create `integrations/llamaindex-loom/` (~200 LOC: LlamaIndex storage-backend interface) and `integrations/crewai-loom/` (~200 LOC: CrewAI shared-memory interface). Each is a separate package (`pyproject.toml` + `tests/` + `README.md`) that **delegates all I/O to `loom-client`**. **No daemon changes.**
- **Test focus:** roundtrip through `loom-client` writes the correct inbox files (mirror `langchain-loom`'s tests).
- **Effort:** ~1 week each. **Expand into:** `docs/plans/<date>-framework-integrations-implementation.md`.

## Feature #9 — Expanded Plugin Examples

- **Goal:** Seed the community contribution surface with high-quality example extractors (the plugin system shipped with only 3, commit `64eeea8`).
- **Files:** Create under `examples/plugins/`: `git_history.py` (~50), `todo_scanner.py` (~40), `test_coverage.py` (~50), `dependency_mapper.py` (~50). Each follows the existing `Extractor` ABC + `plugins.discover()` mechanism. **No daemon changes** (optional: a documented, local-filesystem-only `loom plugins install <url>` ~40 LOC).
- **Test focus:** each example plugin is discovered by `plugins.discover()` and returns entities on a fixture input.
- **Effort:** ~3–4 days. **Expand into:** `docs/plans/<date>-plugin-examples-implementation.md`.

---

# Open Questions (resolve before the relevant phase)

Copied from `plan-inputs.md` — these gate their features:

1. **Cloud offering — Option A (ship managed) or Option B (self-hosted positioning)?** Strategic/business call. Gates Feature #6 (and all cloud work).
2. **P0 order — benchmarks or docs first?** Recommendation: **benchmarks first** (≈2h, harness exists, higher leverage), then docs (≈2 days). Already baked into Phase 1 ordering.
3. **Which P1 module to harden first?** `temporal.py` (strongest "matches Graphiti" claim) vs `patterns.py` (strongest unique-value claim). Gates Feature #4 ordering.
4. **Federation privacy model — per-user or organization-wide?** Affects the Feature #5 index scope under team mode.

---

# Moat Guardrails — What NOT to Change

From the analysis's "Competitive Moat Checklist" + Differentiation Strategy. Any task that appears to require violating one of these is a signal to stop and re-scope.

| Moat | Why it stays |
|------|--------------|
| Filesystem inbox protocol | Deepest differentiator — zero SDK, zero auth. Never gate the inbox behind auth or a required SDK. |
| Single-process daemon | `pip install loom-os && loom start`. No Docker/Neo4j/Postgres in the default path. (Feature #6 Option A is *optional* only.) |
| Per-project isolation | Federation (Feature #5) is **read-only** across projects; never flatten into one namespace or allow cross-writes. |
| Code-specific Graphify AST | Understands real code structure. Incremental persistence + federation enrich it; they never replace it with generic text memory. |
| Dashboard control plane | No memory competitor has a UI. Every user-facing feature keeps a dashboard surface. |
| WebSocket push, not poll | Emit a new event for every new state change; never regress to polling. |
| MCP + inbox dual path | Both integration extremes stay maintained. |

---

# Recommended Sequencing

```
Days 1–3     Phase 1 · Feature #1 (benchmarks) → publish BENCHMARKS.md          [P0]
Days 3–7     Phase 1 · Feature #2 (docs site + Discussions)                     [P0]
Weeks 2–3    Phase 2 · Feature #3 (incremental persistence)                     [P1]
Weeks 3–4    Phase 2 · Feature #4 (module hardening — start temporal|patterns)  [P1]
Weeks 4–6    Phase 2 · Feature #5 (cross-project federation)                    [P1]
Gate         Phase 3 · Feature #6 (cloud DECISION — resolve before cloud work)  [P2]
Weeks 6–7    Phase 3 · Feature #7 (MCP ecosystem tools)                         [P2]
Weeks 7–9    Phase 4 · Features #8–#9 (integrations, plugin examples)           [P3]
Re-analyze   Re-run competitor analysis before Phase 4 ships — category moves weekly.
```

---

# Self-Review (run against the fresh analysis)

- **Spec coverage:** All 9 fresh suggestions mapped to a feature — #1 Benchmarks → F1; #2 Docs → F2; #3 Incremental persistence → F3; #4 Module maturity → F4; #5 Federation → F5; #6 Cloud → F6; #7 MCP → F7; #8 LlamaIndex/CrewAI → F8; #9 Plugin examples → F9. **No gaps.**
- **Placeholder scan:** Phase 1 steps contain real code, real run commands, and expected output. Phases 2–4 are intentionally outlines (per the chosen "one roadmap" shape) and each names the detailed plan to expand into — this is a deliberate altitude choice, not a placeholder.
- **Type consistency:** `shape_metrics(...)` (Task 1.1) produces the dict consumed by `generate_report(systems: list[dict], ...)` (Task 1.2); the `not_measured` flag is defined in 1.2's interface and used in its test. `GraphEngine.build_project/get_stats/hybrid_query` match the verified current signatures in `daemon/graph_engine.py`.
- **Honesty check:** the analysis called Feature #1 "zero new code." This plan adds a *small* amount specifically to stop the current report from publishing fabricated competitor latencies — a credibility fix that is the whole point of "reproducible benchmarks." The zero-code path is documented as an explicit alternative.

---

# Execution Handoff

Plan complete and saved to `docs/plans/2026-07-01-loom-next-moat-roadmap-implementation.md`. Because the chosen shape is **one roadmap (Phase 1 detailed, Phases 2–4 outlined)**, execution proceeds phase-by-phase; expand each Phase-2+ feature into its own detailed plan when you reach it.

Two execution options for **Phase 1** (the ready-to-build part):

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task (1.1 → 2.4), review between tasks, fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
2. **Inline Execution** — execute Phase 1 tasks in this session with checkpoints. REQUIRED SUB-SKILL: `superpowers:executing-plans`.

Which approach?
