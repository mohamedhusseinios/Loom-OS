"""Tests for the ExtractedEdgeStore sidecar."""
import pytest
from daemon.extracted_store import ExtractedEdgeStore
from daemon.extractors import ExtractedEntity


@pytest.mark.asyncio
async def test_add_and_load_extracted_edges(tmp_path):
    store = ExtractedEdgeStore(loom_dir=str(tmp_path))
    ents = [ExtractedEntity(name="AuthService", kind="class", confidence=0.9,
                            relationships=[("uses", "BcryptHasher")])]
    await store.add("proj-1", "finding-abc.md", ents)

    rows = await store.load("proj-1")
    assert len(rows) == 1
    assert rows[0]["name"] == "AuthService"
    assert rows[0]["source"] == "llm"
    assert rows[0]["source_file"] == "finding-abc.md"
    assert rows[0]["relationships"] == [["uses", "BcryptHasher"]]


@pytest.mark.asyncio
async def test_load_missing_project_returns_empty(tmp_path):
    store = ExtractedEdgeStore(loom_dir=str(tmp_path))
    assert await store.load("nope") == []