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
