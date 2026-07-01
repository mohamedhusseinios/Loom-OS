# The knowledge graph

Every project tracked by Loom OS gets its own knowledge graph, built and maintained by [Graphify](https://github.com/nousresearch/graphify). The graph is the thing every connected agent reads from and every finding writes into.

## Graphify runs as a CLI subprocess

`GraphEngine` does **not** call Graphify in-process. Its `__init__` imports the `graphify` package only to set an `available` flag; the actual graph build/update/query work shells out via `subprocess.run(["graphify", ...])`, executed on a worker thread with `asyncio.to_thread` so it doesn't block the daemon's event loop.

- **Full build** — triggered on agent registration (`register.json`) or a manual `POST /api/projects/:id/rebuild`.
- **Incremental update** — triggered when a `finding-*.md` references `files`, rate-limited to one per project per 30 seconds.

## `graphify-out/graph.json` is the source of truth

All graph reads — stats, topology, communities, flows — are served by parsing `<project_path>/graphify-out/graph.json`, the file Graphify itself writes after a build. If that file is absent (e.g. before the first build completes), the relevant endpoints return empty results rather than erroring.

The graph is AST-derived: Graphify parses your codebase's abstract syntax tree with zero API keys required, producing nodes (files, functions, classes) and structural edges (imports, calls, inheritance) — plus community detection and execution-flow analysis.

## LLM-extracted sidecar edges

Structural AST edges only capture what's syntactically visible. To capture semantic relationships mentioned in prose — a finding that says "the auth pipeline uses JWT with Redis-backed sessions" — the daemon runs an **extractor pipeline** over finding/decision bodies:

- `RegexExtractor` — zero-dependency fallback. Finds CamelCase/PascalCase identifiers, snake_case function-call patterns, and a curated dictionary of architecture keywords (factory, singleton, observer, middleware, repository, etc.).
- An optional LLM-backed extractor (Ollama by default, or OpenAI/Claude) for richer entity and relationship extraction — enabled via `pip install loom-os[llm]`.

Extracted entities and relationships are persisted to an `ExtractedEdgeStore` sidecar (not merged into `graph.json` itself) and an `extraction:completed` WebSocket event fires when extraction produces results. At query time, [hybrid search](../guides/hybrid-search.md) merges these sidecar edges into the same adjacency the AST graph uses, so a single traversal spans both AST-derived structure and LLM-extracted semantics.

Community-contributed extractors can plug into this same pipeline — see [Custom extractor plugin](../guides/custom-extractor-plugin.md).

## Querying the graph

- **Natural-language query** — `GET /api/projects/:id/query?q=` shells out to `graphify query "<question>"` and returns matching lines.
- **Hybrid query** — `GraphEngine.hybrid_query` vector-seeds the graph from embeddings, then does a BFS over AST edges *and* extracted sidecar edges, returning rows that carry both semantic (cosine similarity) and structural (BFS depth) relevance. See [Hybrid search](../guides/hybrid-search.md).
- **Dashboard visualization** — the dashboard's graph canvas (`cytoscape` + `cytoscape-cose-bilkent`) renders topology fetched from `GET /api/projects/:id/graph/topology`.

## See also

- [The filesystem protocol](filesystem-protocol.md) — what triggers a graph build/update.
- [Custom extractor plugin](../guides/custom-extractor-plugin.md) — extend the extraction pipeline.
- [API reference](../reference/api.md) — full list of graph-related endpoints.
