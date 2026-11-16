"""Loom agent runtime — chat, suggest, accept, implement glue."""

from __future__ import annotations

import asyncio
import logging
import time

from daemon.agent_credentials import resolve_chat_key
from daemon.llm_client import LlmError, build_llm_client
from daemon.models import (
    AgentChatRequest, AgentChatResponse, AgentTaskStatus, SuggestionStatus,
)
from daemon.orchestrator import (
    LOOM_ACTIONS, Orchestrator, STATUS_FOR_ACTION, SuggestResult, context_hash,
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
            "SELECT default_model, chat_provider, providers_json, api_keys_json FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        return self.registry._settings_from_row(row)

    async def _llm_from_settings(self):
        creds = await self._stored_credentials()
        stored_key, base_url, model, api_style = creds.llm_from_stored()
        provider_id = creds.active_chat_provider_id()
        api_key = resolve_chat_key(provider_id, stored_key)
        return build_llm_client(api_key=api_key, base_url=base_url, api_style=api_style), model

    async def _decision_settings(self) -> tuple[object, dict[str, str]]:
        settings = await self.registry.get_agent_settings(mask_keys=True)
        raw_keys = await self.registry.get_raw_api_keys()
        return settings, raw_keys

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
            settings, raw_keys = await self._decision_settings()
            orch = Orchestrator(self.graph_engine, llm=llm)
            result = await orch.run_suggest_cycle(
                project_path, project_id, task,
                chat_messages=chat_msgs[:-1],
                user_message=payload.message,
                model=model,
                settings=settings,
                raw_keys=raw_keys,
            )
            reply = result.reply
            sug = await self.registry.create_task_suggestion(
                project_id, task.id, result.action_id, result.action_label,
                result.confidence, result.prose, result.catalog, **_suggestion_fields(result),
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
        settings, raw_keys = await self._decision_settings()
        orch = Orchestrator(self.graph_engine, llm=llm)
        result = await orch.run_suggest_cycle(
            project_path, project_id, task, model=model, prefetched_hits=hits,
            settings=settings, raw_keys=raw_keys,
        )
        sug = await self.registry.create_task_suggestion(
            project_id, task.id, result.action_id, result.action_label,
            result.confidence, result.prose, result.catalog, **_suggestion_fields(result),
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
        if sug.status != SuggestionStatus.PENDING:
            raise ValueError("suggestion is not pending")
        updated = await self.registry.set_suggestion_status(suggestion_id, SuggestionStatus.DISMISSED)
        if self.emit_event:
            await self.emit_event("task:suggestion", project_id, updated.model_dump(mode="json") if updated else {})
        return updated

    async def implement(self, project_id: str, task_id: str, spawn_worker=None):
        task = await self.registry.get_agent_task(task_id)
        if task is None:
            raise LookupError("task not found")
        pending = await self.registry.get_pending_suggestion(task_id)
        if pending is not None:
            await self.registry.dismiss_pending_suggestions(task_id)
            if self.emit_event:
                dismissed = await self.registry.get_task_suggestion(pending.id)
                if dismissed is not None:
                    await self.emit_event("task:suggestion", project_id, dismissed.model_dump(mode="json"))
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


def _suggestion_fields(result: SuggestResult) -> dict:
    return {
        "jev_skipped": result.jev_skipped,
        "jev_input_tokens": result.jev_input_tokens,
        "llm_prompt_tokens": result.llm_prompt_tokens,
        "llm_completion_tokens": result.llm_completion_tokens,
        "escalated": result.escalated,
        "context_hash": result.context_hash,
        "filter_provider": result.filter_provider or None,
        "filter_model": result.filter_model or None,
        "judgment_provider": result.judgment_provider or None,
        "judgment_model": result.judgment_model or None,
        "filter_skipped": result.filter_skipped,
        "judgment_skipped": result.judgment_skipped,
        "filter_skip_reason": result.filter_skip_reason,
        "judgment_skip_reason": result.judgment_skip_reason,
        "filter_input_tokens": result.filter_input_tokens,
        "judgment_input_tokens": result.judgment_input_tokens,
        "filter_latency_ms": result.filter_latency_ms,
        "judgment_latency_ms": result.judgment_latency_ms,
        "effective_thresholds_json": result.effective_thresholds_json or None,
    }


class ConflictError(Exception):
    """HTTP 409 — suggestion action incompatible with current task status."""
