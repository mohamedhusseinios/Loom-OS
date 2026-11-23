"""Project-level Loom Agent chat must ground replies in graph memory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from daemon.agent_runtime import AgentRuntime
from daemon.llm_client import LlmError, history_with_reasoning
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
        self.last_reasoning_content = None

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


@pytest.mark.asyncio
async def test_project_chat_stores_and_replays_reasoning_content(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    reg = AgentRegistry(str(tmp_path / "state.db"))
    await reg.initialize()
    await reg.upsert_project("noor", str(tmp_path))
    ge = RecordingGE(hits=[{"id": "n1", "label": "AuthService"}])

    class ReasoningLlm(RecordingLlm):
        def __init__(self):
            super().__init__(reply="first answer")
            self.calls: list[list[dict]] = []

        def chat(self, messages, model=None):
            self.calls.append(list(messages))
            self.called += 1
            self.messages = list(messages)
            if self.called == 1:
                self.last_reasoning_content = "think-step-1"
                self.reply = "first answer"
            else:
                prior = [m for m in messages if m.get("role") == "assistant"]
                assert prior and prior[0].get("reasoning_content") == "think-step-1"
                self.last_reasoning_content = "think-step-2"
                self.reply = "second answer"
            return self.reply

    llm = ReasoningLlm()
    runtime = AgentRuntime(reg, ge)
    try:
        with patch.object(runtime, "_llm_from_settings", return_value=(llm, "beam")):
            first = await runtime.chat("noor", str(tmp_path), AgentChatRequest(message="What is AuthService?"))
            second = await runtime.chat(
                "noor",
                str(tmp_path),
                AgentChatRequest(message="What next?", chat_id=first.chat_id),
            )
            msgs = await reg.list_agent_messages(first.chat_id)
    finally:
        await reg.close()

    assert first.reply == "first answer"
    assert second.reply == "second answer"
    assistants = [m for m in msgs if m.role == "assistant"]
    assert assistants[0].reasoning_content == "think-step-1"
    assert assistants[1].reasoning_content == "think-step-2"
    assert llm.called == 2


@pytest.mark.asyncio
async def test_project_chat_retries_without_history_when_reasoning_missing(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    reg = AgentRegistry(str(tmp_path / "state.db"))
    await reg.initialize()
    await reg.upsert_project("noor", str(tmp_path))
    chat = await reg.create_agent_chat("noor")
    await reg.add_agent_message(chat.id, "user", "old question")
    await reg.add_agent_message(chat.id, "assistant", "old answer")
    ge = RecordingGE(hits=[{"id": "n1", "label": "AuthService"}])

    class FlakyReasoningLlm(RecordingLlm):
        def chat(self, messages, model=None):
            self.called += 1
            self.messages = list(messages)
            if any(m.get("role") == "assistant" for m in messages) and self.called == 1:
                raise LlmError("LLM HTTP 400: missing_required_parameter reasoning_content")
            self.last_reasoning_content = "fresh-reason"
            return "recovered reply"

    llm = FlakyReasoningLlm()
    runtime = AgentRuntime(reg, ge)
    try:
        with patch.object(runtime, "_llm_from_settings", return_value=(llm, "beam")):
            result = await runtime.chat(
                "noor",
                str(tmp_path),
                AgentChatRequest(message="Continue", chat_id=chat.id),
            )
    finally:
        await reg.close()

    assert result.reply == "recovered reply"
    assert llm.called == 2
    assert not any(m.get("role") == "assistant" for m in llm.messages)


def test_history_with_reasoning_preserves_assistant_field():
    msgs = history_with_reasoning([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo", "reasoning_content": "secret-chain"},
    ])
    assert msgs[1]["reasoning_content"] == "secret-chain"
