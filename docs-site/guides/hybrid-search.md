# Hybrid search

Loom OS exposes two search modes over a project's knowledge: plain text/vector search over findings, and a hybrid mode that joins graph structure with vector similarity in one traversal.

## Text mode (default)

```
GET /api/projects/:id/search?q=<query>&mode=text
```

Backed by `AgentRegistry.hybrid_search` (`daemon/registry.py`): scans the project's `finding-*.md` files in the inbox, does a case-insensitive substring match against `q`, and — when an embeddings model is available — also computes cosine similarity between the query and each matching document for ranking. Falls back to text-only results if no embeddings model is loaded.

## Hybrid mode: graph + vector + relational

```
GET /api/projects/:id/search?q=<query>&mode=hybrid
```

This is `GraphEngine.hybrid_query` (`daemon/graph_engine.py`). Unlike text mode, it doesn't just search finding files — it searches the **graph itself**:

1. Reads `<project_path>/graphify-out/graph.json` and builds an adjacency map from AST edges (`links`/`edges`).
2. Merges in relationships from the `ExtractedEdgeStore` sidecar (the LLM/regex-extracted entities described in [The knowledge graph](../concepts/knowledge-graph.md)) — so the traversal spans both AST structure *and* semantic edges pulled from prose.
3. Embeds the query and every node id/label, batching all node embeddings in one call (cached, so repeated queries don't re-embed the whole graph).
4. Seeds the traversal with the highest cosine-similarity nodes.
5. BFS-walks outward from those seeds along the merged adjacency, up to a configurable `depth` (default 2), collecting up to `top_k` (default 10) results.

The result: each row carries **both** semantic relevance (how close the query vector is to the node) and structural relevance (how many hops away it is in the graph) — the same graph+vector(+relational) join that graph-database competitors like Cognee charge for, computed here from a plain `graph.json` file plus a sidecar store, no separate vector database required.

## Using it from the dashboard

The project search UI has a hybrid-mode toggle that switches the `mode` query param between `text` and `hybrid`. Toggle it on when you want results that follow graph relationships (e.g. "what calls into the auth module") rather than plain keyword matches inside findings.

## See also

- [The knowledge graph](../concepts/knowledge-graph.md) — how `graph.json` and the extracted-edge sidecar are built.
- [API reference](../reference/api.md) — the full `/search` endpoint signature alongside the rest of the REST surface.
