"""Embedding pipeline — vector generation and cosine-similarity search.

Design (V1):
- ``EmbeddingGenerator`` wraps sentence-transformers with a graceful fallback
  to zero vectors when the model isn't available (degraded mode).
- ``EmbeddingStore`` uses in-memory NumPy arrays for cosine-similarity search.
  For <10K documents this is fast and requires zero infrastructure.
  A future V2 can swap to an on-disk sqlite-vec backend without changing the
  public API.
"""

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# all-MiniLM-L6-v2 output dimension
_DEFAULT_DIM = 384


class EmbeddingGenerator:
    """Generate text embedding vectors.

    Uses sentence-transformers by default with ``all-MiniLM-L6-v2`` (fast,
    local, free). Falls back to zero vectors in degraded mode.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    async def embed(self, text: str) -> list[float]:
        """Return a 384-dim float embedding for *text*.

        On first call the model is lazy-loaded and cached for subsequent
        calls.  When the model cannot be loaded a zero vector is returned
        (degraded mode — search still works but won't be semantic).
        """
        if self._model is None:
            self._model = self._load_model()

        if self._model is None:
            return [0.0] * _DEFAULT_DIM

        embedding = self._model.encode(text)
        return embedding.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed multiple texts in one model call.

        More efficient than calling embed() N times — the model encodes
        all texts in a single forward pass.
        """
        if self._model is None:
            self._model = self._load_model()
        if self._model is None:
            return [[0.0] * _DEFAULT_DIM for _ in texts]
        embeddings = self._model.encode(texts)
        return [e.tolist() for e in embeddings]

    def _load_model(self):
        """Try to load the sentence-transformer model; return None on failure."""
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.model_name)
            logger.info(
                "EmbeddingGenerator: loaded model %s (dim=%d)",
                self.model_name,
                getattr(model, 'get_sentence_embedding_dimension', lambda: model.get_embedding_dimension())(),
            )
            return model
        except Exception as exc:
            logger.warning(
                "EmbeddingGenerator: cannot load %s — %s. Using zero vectors (degraded mode).",
                self.model_name,
                exc,
            )
            return None


class EmbeddingStore:
    """NumPy-backed vector store for cosine-similarity search.

    Stores (doc_id, text, embedding_array) triplets in memory.  Suitable
    for up to ~10K documents; zero external dependencies.
    """

    def __init__(self, db_path: str = "~/.loom/embeddings.db"):
        self.db_path = Path(db_path).expanduser()
        self._docs: list[tuple[str, str, np.ndarray]] = []

    async def initialize(self):
        """Create the parent directory (future: load persisted vectors)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def insert(self, doc_id: str, text: str, embedding: list[float]):
        """Insert a document with its embedding vector."""
        self._docs.append((doc_id, text, np.array(embedding, dtype=np.float32)))

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return the *top_k* documents by cosine similarity to *query*.

        Returns:
            List of ``{"id": ..., "text": ..., "score": ...}`` sorted by
            descending score.  Empty list when the store is empty or the
            query embedding is a zero vector (degraded mode).
        """
        if not self._docs:
            return []

        gen = EmbeddingGenerator()
        query_vec = np.array(await gen.embed(query), dtype=np.float32)

        # Zero-vector fallback: skip computation
        norm_q = float(np.linalg.norm(query_vec))
        if norm_q == 0.0:
            return []

        results: list[dict] = []
        for doc_id, text, doc_vec in self._docs:
            norm_d = float(np.linalg.norm(doc_vec))
            if norm_d == 0.0:
                continue
            sim = float(np.dot(query_vec, doc_vec) / (norm_q * norm_d))
            results.append({"id": doc_id, "text": text, "score": sim})

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def __len__(self) -> int:
        return len(self._docs)
