"""Orchestrator catalog merge and empty-graph paths."""
import pytest

from daemon.models import AgentTaskRecord, AgentTaskStatus
from daemon.orchestrator import (
    Orchestrator, merge_catalog, loom_catalog_for_status, SuggestResult,
)
from daemon.jev_client import JevClient
from daemon.llm_client import LlmClient


def test_merge_catalog_drops_uncited_candidates():
    loom = [{"id": "loom.move_ready", "label": "Ready", "source": "loom"}]
    pb = [{"id": "play.a", "label": "A", "source": "playbook"}]
    cands = [
        {"id": "x", "label": "X", "graph_ids": ["n1"]},
        {"id": "y", "label": "Y"},  # no citation
    ]
    merged = merge_catalog(loom, pb, cands)
    ids = [m["id"] for m in merged]
    assert ids == ["loom.move_ready", "play.a", "x"]


def test_loom_catalog_filters_by_status():
    ready = loom_catalog_for_status(AgentTaskStatus.READY.value)
    assert any(a["id"] == "loom.move_running" for a in ready)
    assert not any(a["id"] == "loom.move_archived" for a in ready)


@pytest.mark.asyncio
async def test_empty_graph_short_circuit(tmp_path):
    class FakeGE:
        async def hybrid_query(self, *a, **k):
            return []

    task = AgentTaskRecord(
        id="t1", project="p", title="T", instruction="do thing",
        status=AgentTaskStatus.TODO, created_at="now", updated_at="now",
    )
    orch = Orchestrator(
        FakeGE(),
        jev=JevClient(api_key=""),
        llm=LlmClient(api_key=""),
    )
    result = await orch.run_suggest_cycle(str(tmp_path), "p", task)
    assert isinstance(result, SuggestResult)
    assert result.graph_empty is True
    assert "graph" in result.reply.lower()
