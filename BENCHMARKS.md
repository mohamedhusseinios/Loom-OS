# Loom OS Benchmarks

> Reproducible head-to-head measurements. Every number below was measured on the
> same task and repo commit. Cells marked **not measured** were not run — Loom does
> not publish estimated competitor numbers. See `benchmarks/README.md` to reproduce.

## Why Loom is structurally fast

- Single-process daemon — no Docker, no Neo4j, no network round-trips.
- `graph.json` mtime cache — zero repeated JSON parsing.
- NumPy cosine similarity — O(n), no index overhead below ~10K docs.

## Results

| System | Repo @ | Build time | Nodes | Edges | Avg query latency |
|--------|--------|-----------|-------|-------|-------------------|
| loom-os | adea317 | 0.0s | 3,382 | 4,680 | 2179.0ms |
| cognee | — | not measured | not measured | not measured | not measured |
| graphiti | — | not measured | not measured | not measured | not measured |
