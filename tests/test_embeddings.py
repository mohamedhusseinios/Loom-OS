"""Tests for the embedding pipeline."""
import pytest
import numpy as np
from daemon.embeddings import EmbeddingGenerator, EmbeddingStore


@pytest.fixture
def store(tmp_path):
    return EmbeddingStore(db_path=str(tmp_path / "vec.db"))


@pytest.mark.asyncio
async def test_generate_embedding():
    """EmbeddingGenerator produces a float vector of expected dimension."""
    gen = EmbeddingGenerator()
    embedding = await gen.embed("authentication module uses bcrypt")
    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)
    # all-MiniLM-L6-v2 → 384 dimensions
    assert len(embedding) == 384


@pytest.mark.asyncio
async def test_generate_embedding_fallback_without_model():
    """When sentence-transformers is unavailable, returns zero vector gracefully."""
    gen = EmbeddingGenerator(model_name="nonexistent-model-xyz")
    embedding = await gen.embed("hello")
    assert len(embedding) == 384
    assert all(x == 0.0 for x in embedding)


@pytest.mark.asyncio
async def test_store_insert_and_search(store):
    """Inserting embeddings and searching by cosine similarity works."""
    await store.initialize()

    doc_id = "finding-abc"
    text = "Authentication module uses bcrypt for password hashing"
    gen = EmbeddingGenerator()
    embedding = await gen.embed(text)

    await store.insert(doc_id, text, embedding)

    results = await store.search("password hashing security", top_k=3)
    assert len(results) > 0
    assert any(r["id"] == doc_id for r in results)
    # The matching result should have a positive cosine similarity
    first = results[0]
    assert first["score"] > 0


@pytest.mark.asyncio
async def test_store_search_empty_on_no_docs(store):
    """Search returns empty list when no documents are stored."""
    await store.initialize()
    results = await store.search("anything")
    assert results == []


@pytest.mark.asyncio
async def test_store_multiple_inserts_and_search(tmp_path):
    """Multiple documents inserted can be searched with ranking."""
    store = EmbeddingStore(db_path=str(tmp_path / "vec.db"))
    await store.initialize()
    gen = EmbeddingGenerator()

    await store.insert("doc-1", "Authentication with bcrypt", await gen.embed("Authentication with bcrypt"))
    await store.insert("doc-2", "Database migration script", await gen.embed("Database migration script"))
    await store.insert("doc-3", "Password hashing security", await gen.embed("Password hashing security"))

    results = await store.search("password security", top_k=3)
    assert len(results) == 3
    # doc-3 ("Password hashing security") should be the top match
    assert results[0]["id"] == "doc-3"


@pytest.mark.asyncio
async def test_embed_batch_returns_correct_count():
    gen = EmbeddingGenerator()
    texts = ["hello world", "foo bar", "test text"]
    results = await gen.embed_batch(texts)
    assert len(results) == 3
    assert all(len(r) == len(results[0]) for r in results)  # same dim


@pytest.mark.asyncio
async def test_embed_batch_empty_list():
    gen = EmbeddingGenerator()
    results = await gen.embed_batch([])
    assert results == []


def test_embedding_generator_reuses_cached_model_across_instances(monkeypatch):
    """Two EmbeddingGenerator instances with the same model_name share the loaded model."""
    from daemon import embeddings as emb_mod
    emb_mod.clear_model_cache()
    calls = []

    class FakeModel:
        def get_sentence_embedding_dimension(self):
            return 384
        def encode(self, x):
            import numpy as np
            if isinstance(x, list):
                return np.ones((len(x), 384), dtype=np.float32)
            return np.ones(384, dtype=np.float32)

    def fake_loader(model_name):
        calls.append(model_name)
        return FakeModel()

    monkeypatch.setattr(emb_mod, "_instantiate_sentence_transformer", fake_loader)
    g1 = EmbeddingGenerator("all-MiniLM-L6-v2")
    g2 = EmbeddingGenerator("all-MiniLM-L6-v2")
    import asyncio
    asyncio.run(g1.embed("one"))
    asyncio.run(g2.embed("two"))
    assert calls == ["all-MiniLM-L6-v2"]  # loaded once, reused by g2
    emb_mod.clear_model_cache()

