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


@pytest.mark.asyncio
async def test_concurrent_add_is_locked(tmp_path):
    import asyncio
    store = ExtractedEdgeStore(loom_dir=str(tmp_path))
    ents1 = [ExtractedEntity(name="E1", kind="class", confidence=0.9, relationships=[])]
    ents2 = [ExtractedEntity(name="E2", kind="class", confidence=0.9, relationships=[])]

    orig_load = store.load

    async def slow_load(project):
        res = await orig_load(project)
        await asyncio.sleep(0.01)
        return res

    store.load = slow_load

    await asyncio.gather(
        store.add("proj-1", "f1.md", ents1),
        store.add("proj-1", "f2.md", ents2),
    )

    rows = await orig_load("proj-1")
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"E1", "E2"}
