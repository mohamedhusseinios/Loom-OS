"""Project-level Loom Agent chat must ground replies in graph memory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from daemon.agent_runtime import AgentRuntime
from daemon.models import AgentChatRequest
from daemon.registry import AgentRegistry


class RecordingGE:
    def __init__(self, hits=None):
        self.hits = hits if hits is not None else [
            {"id": "n1", "label": "AuthService", "kind": "class"},
            {"id": "n2", "label": "PaymentRouter", "kind": "module"},
        ]
        self.calls: list[tuple] = []

    async def hybrid_query(self, project_path, project, question, top_k=12, **kwargs):
        self.calls.append((project_path, project, question, top_k))
        return list(self.hits)


class RecordingLlm:
    def __init__(self, reply="grounded reply"):
        self.available = True
        self.reply = reply
        self.messages: list[dict] = []
        self.called = 0

    def chat(self, messages, model=None):
        self.called += 1
        self.messages = list(messages)
        return self.reply


@pytest.mark.asyncio
async def test_project_chat_queries_graph_and_injects_context(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    loom = tmp_path / ".loom"
    loom.mkdir()
    (loom / "SHARED_CONTEXT.md").write_text("# Shared\n\nNoor uses Next.js and a payments domain.\n")

    reg = AgentRegistry(str(tmp_path / "state.db"))
    await reg.initialize()
    await reg.upsert_project("noor", str(tmp_path))
    ge = RecordingGE()
    llm = RecordingLlm(reply="Next step: harden PaymentRouter auth.")
    runtime = AgentRuntime(reg, ge)

    try:
        with patch.object(runtime, "_llm_from_settings", return_value=(llm, "deepseek-chat")):
            result = await runtime.chat(
                "noor",
                str(tmp_path),
                AgentChatRequest(message="Review this project and tell me what the best next step is."),
            )
    finally:
        await reg.close()

    assert result.reply == "Next step: harden PaymentRouter auth."
    assert ge.calls, "project chat must call hybrid_query"
    assert ge.calls[0][1] == "noor"
    assert "Review this project" in ge.calls[0][2]
    assert llm.called == 1
    blob = "\n".join(m["content"] for m in llm.messages)
    assert "AuthService" in blob
    assert "PaymentRouter" in blob or "payments domain" in blob.lower()
    assert "Help with project tasks." not in blob


@pytest.mark.asyncio
async def test_project_chat_without_graph_does_not_pretend_ignorance_of_missing_build(tmp_path):
    reg = AgentRegistry(str(tmp_path / "state.db"))
    await reg.initialize()
    await reg.upsert_project("empty", str(tmp_path))
    ge = RecordingGE(hits=[])
    llm = RecordingLlm(reply="should not be called")
    runtime = AgentRuntime(reg, ge)

    try:
        with patch.object(runtime, "_llm_from_settings", return_value=(llm, "deepseek-chat")):
            result = await runtime.chat(
                "empty",
                str(tmp_path),
                AgentChatRequest(message="What should we build next?"),
            )
    finally:
        await reg.close()

    assert llm.called == 0
    assert "graph" in result.reply.lower()
