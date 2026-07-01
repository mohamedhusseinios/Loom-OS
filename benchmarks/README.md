# Loom OS Benchmarks — Reproduction Guide

This document is the runbook for regenerating every number in the root
[`BENCHMARKS.md`](../BENCHMARKS.md). The guiding rule: **we never publish a
competitor number we did not measure ourselves.** If a system could not be
stood up, its row renders `not measured` — see [Combine + render](#5-combine--render)
below.

All commands assume you start at the repo root
(`/Users/mohamedabdulrahman/Mohamed-Hussien/my-projects/agentic-os` on the
machine this guide was written on, but any checkout works).

## Contents

1. [Loom run](#1-loom-run)
2. [Pinned reference corpus](#2-pinned-reference-corpus)
3. [Cognee](#3-cognee)
4. [Graphiti](#4-graphiti)
5. [Combine + render](#5-combine--render)
6. [Hardware note](#6-hardware-note)

---

## 1. Loom run

Prerequisites:

- The project's `.venv` is created and active (`python3 -m venv .venv && source
  .venv/bin/activate && pip install -e ".[dev]"`, per the root `CLAUDE.md`).
- The `graphify` CLI is on `PATH` (Loom's `GraphEngine` shells out to it as a
  subprocess — it is not a Python import). Check with `which graphify`; if
  missing, install it per its own docs before continuing.

Run the harness against the pinned corpus (see [section 2](#2-pinned-reference-corpus)
for `<repo_path>`):

```bash
.venv/bin/python -m benchmarks.harness <repo_path> > benchmarks/loom.json
```

`benchmarks/harness.py` builds the graph via `GraphEngine.build_project`,
times it, reads back stats via `get_stats`, then runs four fixed queries
("authentication", "database", "error handling", "main entry point") through
`hybrid_query` and times each. It prints a single JSON metrics object to
stdout — hence the `>` redirect into `benchmarks/loom.json`.

## 2. Pinned reference corpus

Every system in the comparison must ingest **the exact same tree** — same
repo, same commit — or the numbers aren't comparable. Pin one public repo at
one commit and reuse that checkout for Loom, Cognee, and Graphiti:

```bash
git clone https://github.com/<owner>/<repo>.git /tmp/bench-corpus
git -C /tmp/bench-corpus checkout <sha>
```

Record the resulting short SHA — `git -C /tmp/bench-corpus rev-parse --short HEAD`
— in whatever notes accompany your benchmark run. Note that `benchmarks/harness.py`
also captures this SHA automatically (`repo_sha` field, via `git rev-parse
--short HEAD` on `<repo_path>`) and stamps it into `loom.json`, so as long as
Cognee's and Graphiti's metrics JSON report the *same* SHA, readers can
confirm all three systems ran against identical input.

Pick a corpus that's realistic but bounded — large enough to be a meaningful
build (thousands of files, not a toy), small enough that Cognee/Graphiti
ingestion finishes in a reasonable time on your hardware.

## 3. Cognee

> Example — adjust to your installed Cognee version. Cognee's Docker topology
> and Python API have changed across releases; treat the snippets below as a
> starting point, not a pinned contract.

Bring up the backing stores (Cognee typically needs a graph store and a
vector store — Neo4j and PGVector are common choices):

```yaml
# docker-compose.cognee.yml — example, adjust to your installed Cognee version
services:
  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/bench-password
    ports:
      - "7474:7474"
      - "7687:7687"
  pgvector:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: cognee
      POSTGRES_PASSWORD: bench-password
      POSTGRES_DB: cognee
    ports:
      - "5432:5432"
```

```bash
docker compose -f docker-compose.cognee.yml up -d
```

Ingest the same pinned corpus from [section 2](#2-pinned-reference-corpus) and
time both the build and a fixed query set, then shape the result into the
Task 1.1 schema (the same keys `benchmarks/harness.py` emits):

```python
# example — adjust import paths / API calls to your installed cognee version
import time, json, subprocess
import cognee

repo_path = "/tmp/bench-corpus"
repo_sha = subprocess.run(
    ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
    capture_output=True, text=True,
).stdout.strip()

t0 = time.monotonic()
await cognee.add(repo_path)
await cognee.cognify()
build_time_s = time.monotonic() - t0

queries = ["authentication", "database", "error handling", "main entry point"]
latencies_ms = []
for q in queries:
    t0 = time.monotonic()
    await cognee.search(q)
    latencies_ms.append((time.monotonic() - t0) * 1000)

metrics = {
    "system": "cognee",
    "repo_sha": repo_sha,
    "build_time_s": round(build_time_s, 2),
    "nodes": ...,          # pull from Cognee's graph store (e.g. a Neo4j COUNT query)
    "edges": ...,          # same
    "communities": ...,    # same, if Cognee exposes community detection; else 0
    "avg_query_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 1),
    "queries_run": len(latencies_ms),
}
json.dump(metrics, open("benchmarks/cognee.json", "w"), indent=2)
```

The four query strings intentionally match `benchmarks/harness.py`'s fixed
query set so the `avg_query_latency_ms` numbers are comparing like for like.

If you cannot stand Cognee up at all (dependency conflicts, no Docker on the
box, etc.), don't fabricate a number — write the "not measured" stub instead:

```bash
echo '{"system": "cognee", "not_measured": true}' > benchmarks/cognee.json
```

## 4. Graphiti

> Example — adjust to your installed Graphiti version, same caveat as Cognee
> above.

Graphiti is Neo4j-backed; bring up just the graph store:

```yaml
# docker-compose.graphiti.yml — example, adjust to your installed Graphiti version
services:
  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/bench-password
    ports:
      - "7474:7474"
      - "7687:7687"
```

```bash
docker compose -f docker-compose.graphiti.yml up -d
```

Ingest the same pinned corpus and time build + queries, emitting the same
schema (`"system": "graphiti"`):

```python
# example — adjust import paths / API calls to your installed graphiti version
import time, json, subprocess
from graphiti_core import Graphiti

repo_path = "/tmp/bench-corpus"
repo_sha = subprocess.run(
    ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
    capture_output=True, text=True,
).stdout.strip()

graphiti = Graphiti("bolt://localhost:7687", "neo4j", "bench-password")

t0 = time.monotonic()
# add_episode (or equivalent ingestion call) once per file/chunk of repo_path
await graphiti.build_indices_and_constraints()
# ... ingest loop over repo_path ...
build_time_s = time.monotonic() - t0

queries = ["authentication", "database", "error handling", "main entry point"]
latencies_ms = []
for q in queries:
    t0 = time.monotonic()
    await graphiti.search(q)
    latencies_ms.append((time.monotonic() - t0) * 1000)

metrics = {
    "system": "graphiti",
    "repo_sha": repo_sha,
    "build_time_s": round(build_time_s, 2),
    "nodes": ...,          # e.g. MATCH (n) RETURN count(n) against the Neo4j instance
    "edges": ...,          # e.g. MATCH ()-[r]->() RETURN count(r)
    "communities": ...,    # if Graphiti's community-detection is enabled; else 0
    "avg_query_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 1),
    "queries_run": len(latencies_ms),
}
json.dump(metrics, open("benchmarks/graphiti.json", "w"), indent=2)
```

If Graphiti can't be stood up on your hardware/dependency set, write the stub
instead of guessing:

```bash
echo '{"system": "graphiti", "not_measured": true}' > benchmarks/graphiti.json
```

## 5. Combine + render

Once you have `benchmarks/loom.json` and, if measured, `benchmarks/cognee.json`
and `benchmarks/graphiti.json`, render the root `BENCHMARKS.md` table with
`benchmarks/report.py`'s `generate_report`, which takes a **list** of metrics
dicts (one per system) and writes `BENCHMARKS.md` at the repo root by default:

```bash
.venv/bin/python -c "
import json
from benchmarks.report import generate_report
generate_report([json.load(open('benchmarks/loom.json')), {'system':'cognee','not_measured':True}, {'system':'graphiti','not_measured':True}])
"
```

Swap in the real `cognee.json` / `graphiti.json` loads for any system you
actually measured, e.g.:

```bash
.venv/bin/python -c "
import json
from benchmarks.report import generate_report
generate_report([
    json.load(open('benchmarks/loom.json')),
    json.load(open('benchmarks/cognee.json')),
    json.load(open('benchmarks/graphiti.json')),
])
"
```

`generate_report` (in `benchmarks/report.py`) treats any dict with
`"not_measured": true` specially: every cell in that system's row renders the
literal string **"not measured"** instead of a number, and its SHA column
renders `—`. This is deliberate and load-bearing for honesty: **we do not
estimate or extrapolate competitor numbers we didn't run ourselves.** A
`not_measured` row is not a placeholder to be filled in later with a guess —
it's the correct, final state for a system nobody in this project has
actually benchmarked yet.

## 6. Hardware note

Benchmark numbers are only interpretable next to the hardware they were
measured on. Record, at minimum, CPU core count, RAM, OS, and Python version
alongside every run. Example (the machine this guide was authored on):

- **CPU:** Apple Silicon, 12 cores
- **RAM:** 24 GB
- **OS:** macOS 26.6 (Darwin 25.6.0, arm64)
- **Python:** 3.14.5

Docker-backed systems (Cognee, Graphiti) are additionally sensitive to
whatever resource limits your Docker/OrbStack/Colima runtime enforces on
containers — note those too if you constrain them, since a starved container
will inflate `build_time_s` and `avg_query_latency_ms` for reasons that have
nothing to do with the system under test.
