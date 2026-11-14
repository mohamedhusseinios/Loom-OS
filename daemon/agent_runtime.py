"""Loom agent runtime — chat, suggest, accept, implement glue."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from daemon.agent_credentials import (
    resolve_deepseek_key,
    resolve_typesafe_base_url,
    resolve_typesafe_key,
)
from daemon.jev_client import JevClient
from daemon.llm_client import LlmClient, LlmError
from daemon.models import (
    AgentChatRequest, AgentChatResponse, AgentTaskStatus, SuggestionStatus,
)
from daemon.orchestrator import (
    LOOM_ACTIONS, Orchestrator, STATUS_FOR_ACTION, context_hash,
)

logger = logging.getLogger("loom.agent_runtime")

# task_id -> last auto-suggest monotonic time
_suggest_cooldown: dict[str, float] = {}
SUGGEST_COOLDOWN_SEC = 30.0


class AgentRuntime:
    def __init__(self, registry, graph_engine, emit_event=None):
        self.registry = registry
        self.graph_engine = graph_engine
        self.emit_event = emit_event  # async callable(event, project, data)

    async def _task_hits(self, project_path: str, project_id: str, task) -> list[dict]:
        if self.graph_engine is None:
            return []
        question = f"{task.title}\n{task.instruction}"
        try:
            return await self.graph_engine.hybrid_query(project_path, project_id, question, top_k=12)
        except Exception:
            logger.warning("hybrid_query failed while hashing context", exc_info=True)
            return []

    async def _stored_credentials(self):
        cursor = await self.registry.db.execute(
            "SELECT default_model, providers_json, api_keys_json FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        return self.registry._settings_from_row(row)

    async def _llm_from_settings(self) -> tuple[LlmClient, str]:
        creds = await self._stored_credentials()
        stored_key, base_url, model = creds.llm_from_stored()
        api_key = resolve_deepseek_key(stored_key)
        return LlmClient(api_key=api_key, base_url=base_url), model

    async def _jev_from_settings(self) -> JevClient:
        creds = await self._stored_credentials()
        return JevClient(
            api_key=resolve_typesafe_key(creds.typesafe_key) or None,
            base_url=resolve_typesafe_base_url(creds.typesafe_base_url),
        )

    async def chat(self, project_id: str, project_path: str, payload: AgentChatRequest) -> AgentChatResponse:
        llm, model = await self._llm_from_settings()
        if not llm.available:
            raise LlmError("API key not configured — add it in Agent settings")

        chat = None
        if payload.chat_id:
            chat = await self.registry.get_agent_chat(payload.chat_id)
        if chat is None:
            chat = await self.registry.create_agent_chat(project_id, task_id=payload.task_id)

        await self.registry.add_agent_message(chat.id, "user", payload.message)
        history = await self.registry.list_agent_messages(chat.id)
        chat_msgs = [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]

        suggestion_id = None
        reply = ""
        if payload.task_id:
            task = await self.registry.get_agent_task(payload.task_id)
            if task is None:
                raise ValueError(f"task not found: {payload.task_id}")
            orch = Orchestrator(self.graph_engine, jev=await self._jev_from_settings(), llm=llm)
            result = await orch.run_suggest_cycle(
                project_path, project_id, task,
                chat_messages=chat_msgs[:-1],
                user_message=payload.message,
                model=model,
            )
            reply = result.reply
            sug = await self.registry.create_task_suggestion(
                project_id, task.id, result.action_id, result.action_label,
                result.confidence, result.prose, result.catalog, result.jev_skipped,
                jev_input_tokens=result.jev_input_tokens,
                llm_prompt_tokens=result.llm_prompt_tokens,
                llm_completion_tokens=result.llm_completion_tokens,
                escalated=result.escalated,
                context_hash=result.context_hash,
            )
            suggestion_id = sug.id
            if self.emit_event:
                await self.emit_event("task:suggestion", project_id, sug.model_dump(mode="json"))
        else:
            messages = [{"role": "system", "content": "You are the Loom agent. Help with project tasks."}]
            messages.extend(chat_msgs)
            reply = await asyncio.to_thread(llm.chat, messages, model)

        await self.registry.add_agent_message(chat.id, "assistant", reply)
        if self.emit_event:
            await self.emit_event("agent:message", project_id, {
                "chat_id": chat.id, "role": "assistant", "content": reply,
            })
        return AgentChatResponse(chat_id=chat.id, reply=reply, suggestion_id=suggestion_id)

    async def suggest(self, project_id: str, project_path: str, task_id: str, force: bool = True):
        task = await self.registry.get_agent_task(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")
        hits = await self._task_hits(project_path, project_id, task)
        ctx_hash = context_hash(task, hits)
        if not force:
            pending = await self.registry.get_pending_suggestion(task_id)
            last = _suggest_cooldown.get(task_id, 0)
            if pending and (time.monotonic() - last) < SUGGEST_COOLDOWN_SEC:
                return pending
            if pending and pending.context_hash and pending.context_hash == ctx_hash:
                logger.info("auto-suggest skipped; context hash unchanged for task %s", task_id)
                return pending
        llm, model = await self._llm_from_settings()
        orch = Orchestrator(self.graph_engine, jev=await self._jev_from_settings(), llm=llm)
        result = await orch.run_suggest_cycle(
            project_path, project_id, task, model=model, prefetched_hits=hits,
        )
        sug = await self.registry.create_task_suggestion(
            project_id, task.id, result.action_id, result.action_label,
            result.confidence, result.prose, result.catalog, result.jev_skipped,
            jev_input_tokens=result.jev_input_tokens,
            llm_prompt_tokens=result.llm_prompt_tokens,
            llm_completion_tokens=result.llm_completion_tokens,
            escalated=result.escalated,
            context_hash=result.context_hash,
        )
        _suggest_cooldown[task_id] = time.monotonic()
        if self.emit_event:
            await self.emit_event("task:suggestion", project_id, sug.model_dump(mode="json"))
        return sug

    async def accept_suggestion(self, project_id: str, suggestion_id: str):
        sug = await self.registry.get_task_suggestion(suggestion_id)
        if sug is None or sug.project != project_id:
            raise LookupError("suggestion not found")
        if sug.status != SuggestionStatus.PENDING:
            raise ValueError("suggestion is not pending")
        task = await self.registry.get_agent_task(sug.task_id)
        if task is None:
            raise LookupError("task not found")
        target = STATUS_FOR_ACTION.get(sug.action_id)
        if target is not None:
            allowed_ids = {aid for aid, _ in LOOM_ACTIONS.get(task.status.value, [])}
            if sug.action_id not in allowed_ids:
                raise ConflictError(f"action {sug.action_id} incompatible with status {task.status.value}")
            await self.registry.update_agent_task(task.id, status=target)
        updated = await self.registry.set_suggestion_status(suggestion_id, SuggestionStatus.ACCEPTED)
        if self.emit_event:
            await self.emit_event("task:suggestion", project_id, updated.model_dump(mode="json") if updated else {})
            task2 = await self.registry.get_agent_task(sug.task_id)
            if task2:
                await self.emit_event("task:updated", project_id, task2.model_dump(mode="json"))
        return updated

    async def dismiss_suggestion(self, project_id: str, suggestion_id: str):
        sug = await self.registry.get_task_suggestion(suggestion_id)
        if sug is None or sug.project != project_id:
            raise LookupError("suggestion not found")
        return await self.registry.set_suggestion_status(suggestion_id, SuggestionStatus.DISMISSED)

    async def implement(self, project_id: str, task_id: str, spawn_worker=None):
        task = await self.registry.get_agent_task(task_id)
        if task is None:
            raise LookupError("task not found")
        assignee = f"loom-agent-{project_id}"
        await self.registry.update_agent_task(
            task_id, status=AgentTaskStatus.RUNNING, assignee=assignee,
        )
        # Ensure agent row exists for worker routing
        from daemon.models import AgentInfo
        await self.registry.upsert_agent(AgentInfo(
            agent_id=assignee,
            agent_name="loom-agent",
            version="1.0",
            project=project_id,
            capabilities=["chat", "implement", "orchestration"],
        ))
        updated = await self.registry.get_agent_task(task_id)
        if spawn_worker and updated:
            spawn_worker(updated)
        if self.emit_event and updated:
            await self.emit_event("task:updated", project_id, updated.model_dump(mode="json"))
        return updated


class ConflictError(Exception):
    """HTTP 409 — suggestion action incompatible with current task status."""
