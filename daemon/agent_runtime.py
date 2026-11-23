"""Loom agent runtime — chat, suggest, accept, implement glue."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import coding_agent.patterns as patterns_pkg
from coding_agent.patterns import load_patterns
from coding_agent.selection import RankedStrategy
from coding_agent.session import DEFAULT_COST_LIMIT_USD, DEFAULT_STEP_LIMIT, DEFAULT_TOKEN_LIMIT
from daemon.agent_credentials import DEEPSEEK_PROVIDER_ID, resolve_deepseek_key
from daemon.decision import NullDecisionClient, DecisionClient, build_decision_clients, resolve_decision_config
from daemon.llm_client import LlmClient, LlmError
from daemon.models import (
    AgentChatRequest, AgentChatResponse, AgentTaskStatus, ImplementRequest, SuggestionStatus,
)
from daemon.pattern_selection import CLIENT_SNAPSHOT_WHY, FALLBACK_FAMILY_ID, FALLBACK_WHY, SelectionPreview, preview_strategies
from daemon.orchestrator import (
    LOOM_ACTIONS, Orchestrator, STATUS_FOR_ACTION, SuggestResult, context_hash,
)

logger = logging.getLogger("loom.agent_runtime")

FAMILIES_DIR = Path(patterns_pkg.__file__).parent / "families"


@dataclass
class LockedSelection:
    family_id: str
    modifier_ids: list[str]
    chosen_source: str  # user | auto | fallback_default
    user_override: bool
    preview: SelectionPreview | None
    runner_key: str = FALLBACK_FAMILY_ID

# task_id -> last auto-suggest monotonic time
_suggest_cooldown: dict[str, float] = {}
SUGGEST_COOLDOWN_SEC = 30.0


def loom_run_dir(run_id: str) -> Path:
    return Path.home() / ".loom" / "runs" / run_id


def read_new_jsonl_lines(path: Path, offset: int = 0) -> tuple[list[dict], int]:
    """Return complete JSON objects appended after ``offset`` and the new byte offset."""
    if offset < 0:
        offset = 0
    if not path.is_file():
        return [], offset
    with path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read()
    if not raw:
        return [], offset
    if not raw.endswith(b"\n"):
        cut = raw.rfind(b"\n")
        if cut == -1:
            return [], offset
        raw = raw[: cut + 1]
    events: list[dict] = []
    for line in raw.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events, offset + len(raw)


class JsonlEventTail:
    """Byte-offset tail of one or more JSONL sinks. Safe to feed a growing file."""

    def __init__(self) -> None:
        self._offsets: dict[str, int] = {}

    def poll(self, path: Path) -> list[dict]:
        key = str(path)
        events, offset = read_new_jsonl_lines(Path(path), self._offsets.get(key, 0))
        self._offsets[key] = offset
        return events


async def emit_new_run_events(path: Path, tail: JsonlEventTail, emit_event, project: str, run_id: str, task_id: str) -> int:
    events = tail.poll(path)
    for payload in events:
        if emit_event:
            await emit_event("agent:run_event", project, {
                "run_id": run_id, "task_id": task_id, "payload": payload,
            })
    return len(events)


_TERMINAL_STATUS = {
    "run.succeeded": "succeeded",
    "run.failed": "failed",
    "run.cancelled": "cancelled",
}
_OPEN_RUN_STATUSES = ("running", "cancelling")


def _terminal_status(events: list[dict]) -> tuple[str, str] | None:
    found = None
    for payload in events:
        status = _TERMINAL_STATUS.get(payload.get("type"))
        if status:
            found = (status, str(payload.get("stop_reason") or status))
    return found


def _manifest_prompt(instruction: str, criteria: str) -> str:
    text = instruction or ""
    if criteria:
        return f"{text}\n\nAcceptance criteria:\n{criteria}"
    return text


_DEFAULT_TEST_COMMAND = ["python", "-m", "pytest", "-q"]
_DEFAULT_LINT_COMMAND = ["python", "-m", "ruff", "check", "."]


async def seal_exited_worker_runs(registry, supervisor, emit_event, tail: JsonlEventTail) -> int:
    """Write a terminal JSONL event for open runs whose worker has already exited."""
    if supervisor is None or not hasattr(supervisor, "exited_task_ids"):
        return 0
    exited = set(supervisor.exited_task_ids())
    if not exited:
        return 0
    from daemon.agent_run import ensure_terminal_event, seal_manifest_run

    sealed = 0
    for status in _OPEN_RUN_STATUSES:
        for run in await registry.list_agent_runs(status=status):
            if run.task_id not in exited or not run.run_dir:
                continue
            manifest = Path(run.run_dir) / "manifest.json"
            if manifest.is_file():
                seal_manifest_run(str(manifest))
            else:
                ensure_terminal_event(Path(run.run_dir) / "events.jsonl", "run.failed", "worker_exit")
            await drain_run_jsonl(run, tail, emit_event, registry)
            sealed += 1
    if hasattr(supervisor, "forget_exited"):
        still: set[str] = set()
        for status in _OPEN_RUN_STATUSES:
            for run in await registry.list_agent_runs(status=status):
                if run.task_id in exited:
                    still.add(run.task_id)
        supervisor.forget_exited(exited - still)
    return sealed


async def drain_run_jsonl(run, tail: JsonlEventTail, emit_event, registry) -> list[dict]:
    """Emit new JSONL lines. A terminal event closes a running or cancelling row."""
    events = tail.poll(Path(run.run_dir) / "events.jsonl")
    for payload in events:
        if emit_event:
            await emit_event("agent:run_event", run.project, {
                "run_id": run.id, "task_id": run.task_id, "payload": payload,
            })
    terminal = _terminal_status(events)
    if terminal is not None and run.status in _OPEN_RUN_STATUSES:
        status, reason = terminal
        await registry.update_agent_run(run.id, status=status, stop_reason=reason)
    return events


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
        stored_key, base_url, model, provider_id = creds.llm_from_stored()
        api_key = self._resolve_chat_key(stored_key, provider_id)
        return LlmClient(api_key=api_key, base_url=base_url), model

    @staticmethod
    def _resolve_chat_key(stored_key: str, provider_id: str) -> str:
        """Env fallback is DeepSeek-only; custom providers never inherit ``DEEPSEEK_API_KEY``."""
        if provider_id == DEEPSEEK_PROVIDER_ID:
            return resolve_deepseek_key(stored_key)
        return stored_key

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

    def _selection_clients(self, settings, raw_keys) -> tuple[DecisionClient, DecisionClient]:
        try:
            config = resolve_decision_config(settings, raw_keys)
            return build_decision_clients(config)
        except Exception:
            logger.warning("decision config unavailable; selection will fall back to react", exc_info=True)
            null = NullDecisionClient()
            return null, null

    def _synthetic_preview(self, reason: str) -> SelectionPreview:
        preview = SelectionPreview(fallback=True, skip_reason=reason)
        react = RankedStrategy(family_id=FALLBACK_FAMILY_ID, modifier_ids=[], fit="High", why=[FALLBACK_WHY], expected_cost_class=None, name="ReAct")
        preview.ranked, preview.top3, preview.recommended = [react], [react], react
        preview.auto_decidable = True
        return preview

    async def _preview_with(self, task, settings, raw_keys, registry) -> SelectionPreview:
        relevance, judgment = self._selection_clients(settings, raw_keys)
        return await preview_strategies(
            task_instruction=task.instruction or "",
            acceptance_criteria=getattr(task, "acceptance_criteria", "") or "",
            registry=registry, relevance=relevance, judgment=judgment,
            available_capabilities=set(),
            autonomy_min_fit=settings.autonomy_min_fit,
            autonomy_require_margin=settings.autonomy_require_margin,
        )

    async def preview_selection(self, task) -> SelectionPreview:
        """Stateless strategy preview. Never raises on settings/pattern/provider failure (falls back to react)."""
        try:
            settings, raw_keys = await self._decision_settings()
            registry = load_patterns(FAMILIES_DIR)
            return await self._preview_with(task, settings, raw_keys, registry)
        except Exception:
            logger.warning("strategy preview failed; falling back to react", exc_info=True)
            return self._synthetic_preview("error")

    def _fallback_lock(self, preview: SelectionPreview) -> LockedSelection:
        return LockedSelection(family_id=FALLBACK_FAMILY_ID, modifier_ids=[], chosen_source="fallback_default", user_override=False, preview=preview, runner_key=FALLBACK_FAMILY_ID)

    async def _resolve_selection(self, task, request: ImplementRequest) -> LockedSelection:
        try:
            registry = load_patterns(FAMILIES_DIR)
            active = {doc.id: doc for doc in registry.active_families()}
            if request.choice == "user":
                # The client already holds a preview; never re-score on the user path.
                return self._lock_user_pick(request, self._client_snapshot_preview(request, active), active)
            settings, raw_keys = await self._decision_settings()
            try:
                preview = await self._preview_with(task, settings, raw_keys, registry)
            except Exception:
                logger.warning("strategy preview failed; falling back to react", exc_info=True)
                preview = self._synthetic_preview("error")
            return self._lock_from_preview(request, preview, active, settings.selection_autonomy_enabled)
        except (SelectionConflict, ValueError):
            raise
        except Exception:
            logger.warning("selection setup failed; falling back to react", exc_info=True)
            return self._fallback_lock(self._synthetic_preview("error"))

    def _client_snapshot_preview(self, request: ImplementRequest, active: dict) -> SelectionPreview:
        """Preview stand-in built from the client's recommendation snapshot (no provider calls)."""
        preview = SelectionPreview()
        doc = active.get(request.recommended_family_id) if request.recommended_family_id else None
        if doc is not None:
            rec = RankedStrategy(family_id=doc.id, modifier_ids=[], fit="Medium", why=[CLIENT_SNAPSHOT_WHY], expected_cost_class=doc.expected_cost_class, name=doc.name)
            preview.ranked, preview.top3, preview.recommended = [rec], [rec], rec
        return preview

    def _lock_user_pick(self, request: ImplementRequest, preview: SelectionPreview, active: dict) -> LockedSelection:
        if not request.family_id or request.family_id not in active:
            raise ValueError(f"family_id must be one of the active families: {sorted(active)}")
        doc = active[request.family_id]
        override = request.recommended_family_id is not None and request.family_id != request.recommended_family_id
        return LockedSelection(family_id=request.family_id, modifier_ids=list(request.modifier_ids), chosen_source="user", user_override=override, preview=preview, runner_key=doc.runner or doc.id)

    def _lock_from_preview(self, request: ImplementRequest, preview: SelectionPreview, active: dict, autonomy_enabled: bool) -> LockedSelection:
        recommended = preview.recommended

        def lock(family_id: str, modifier_ids: list[str], source: str, override: bool) -> LockedSelection:
            doc = active.get(family_id)
            runner_key = (doc.runner or doc.id) if doc is not None else family_id
            return LockedSelection(family_id=family_id, modifier_ids=modifier_ids, chosen_source=source, user_override=override, preview=preview, runner_key=runner_key)

        if request.choice == "user":
            return self._lock_user_pick(request, preview, active)
        if preview.fallback:
            return self._fallback_lock(preview)
        # "delegate" never conflicts: it accepts the recommendation even when not auto-decidable.
        if request.choice == "auto" and not preview.auto_decidable and autonomy_enabled:
            raise SelectionConflict(preview)
        if recommended is not None and recommended.family_id in active:
            return lock(recommended.family_id, list(recommended.modifier_ids), "auto", False)
        return self._fallback_lock(preview)

    async def implement(self, project_id: str, task_id: str, spawn_worker=None, request: ImplementRequest | None = None, worker_live=None):
        task = await self.registry.get_agent_task(task_id)
        if task is None or task.project != project_id:
            raise LookupError("task not found")
        if worker_live is not None and worker_live(task_id):
            raise ConflictError("a worker is already running for this task")
        selection = await self._resolve_selection(task, request or ImplementRequest())
        pending = await self.registry.get_pending_suggestion(task_id)
        if pending is not None:
            await self.registry.dismiss_pending_suggestions(task_id)
            if self.emit_event:
                dismissed = await self.registry.get_task_suggestion(pending.id)
                if dismissed is not None:
                    await self.emit_event("task:suggestion", project_id, dismissed.model_dump(mode="json"))
        assignee = f"loom-agent-{project_id}"
        manifest_path = None
        updated = await self.registry.get_agent_task(task_id)
        if updated:
            manifest_path = await self._open_coding_run(project_id, updated, selection)
            from daemon.models import AgentInfo
            await self.registry.update_agent_task(
                task_id, status=AgentTaskStatus.RUNNING, assignee=assignee,
            )
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
        return updated, manifest_path

    async def _open_coding_run(self, project_id: str, task, selection: LockedSelection | None = None) -> str:
        if selection is None:
            selection = LockedSelection(family_id=FALLBACK_FAMILY_ID, modifier_ids=[], chosen_source="fallback_default", user_override=False, preview=None)
        preview = selection.preview
        runner_fallback = selection.runner_key != FALLBACK_FAMILY_ID
        telemetry = _selection_telemetry(selection)
        run_id = str(uuid.uuid4())
        run_dir = loom_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        cancel_path = run_dir / "cancel"
        events_path = run_dir / "events.jsonl"
        manifest = {
            "family_id": selection.family_id,
            "modifier_ids": list(selection.modifier_ids),
            "runner_fallback": runner_fallback,
            "chosen_source": selection.chosen_source,
            "user_override": selection.user_override,
            "selection": telemetry,
            "step_limit": DEFAULT_STEP_LIMIT,
            "token_limit": DEFAULT_TOKEN_LIMIT,
            "cost_limit": DEFAULT_COST_LIMIT_USD,
            "cost_limit_usd": DEFAULT_COST_LIMIT_USD,
            "prompt": _manifest_prompt(task.instruction, getattr(task, "acceptance_criteria", "") or ""),
            "cancel_path": str(cancel_path),
            "run_dir": str(run_dir),
            "events_path": str(events_path),
            "worktree_path": task.workspace_path or "",
            "task_id": task.id,
            "project": project_id,
            "test_command": list(_DEFAULT_TEST_COMMAND),
            "lint_command": list(_DEFAULT_LINT_COMMAND),
        }
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Manifest belongs to the worker spawn env, never the daemon process.
        os.environ.pop("LOOM_AGENT_MANIFEST", None)
        await self.registry.create_agent_run(
            task_id=task.id, project=project_id, run_dir=str(run_dir),
            worktree_path=task.workspace_path, family_id=selection.family_id,
            modifier_ids_json=json.dumps(list(selection.modifier_ids)),
            chosen_source=selection.chosen_source, user_override=selection.user_override,
            status="running", step_limit=DEFAULT_STEP_LIMIT, token_limit=DEFAULT_TOKEN_LIMIT,
            cost_limit=DEFAULT_COST_LIMIT_USD, run_id=run_id,
            **_selection_run_columns(preview),
        )
        return str(manifest_path)

    async def cancel_run(self, project_id: str, run_id: str, tail: JsonlEventTail | None = None):
        run = await self.registry.get_agent_run(run_id)
        if run is None or run.project != project_id:
            raise LookupError("run not found")
        flag = Path(run.run_dir) / "cancel"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("cancelled\n", encoding="utf-8")
        await drain_run_jsonl(run, tail or JsonlEventTail(), self.emit_event, self.registry)
        fresh = await self.registry.get_agent_run(run_id)
        if fresh and fresh.status in _TERMINAL_STATUS.values():
            return fresh
        # Stay visible to the JSONL tail until the worker writes run.cancelled.
        return await self.registry.update_agent_run(run_id, status="cancelling", if_status="running")


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


def selection_preview_to_dict(preview: SelectionPreview) -> dict:
    return dataclasses.asdict(preview)


def _selection_telemetry(selection: LockedSelection) -> dict:
    preview = selection.preview
    if preview is None:
        return {"chosen_source": selection.chosen_source}
    data = selection_preview_to_dict(preview)
    return {
        "chosen_source": selection.chosen_source,
        "user_override": selection.user_override,
        "recommended": data["recommended"],
        "scores": data["scores"],
        "fallback": data["fallback"],
        "skip_reason": data["skip_reason"],
        "stage1_profile": data["stage1_profile"],
        "stage1_provider": data["stage1_provider"],
        "stage2_provider": data["stage2_provider"],
    }


def _selection_run_columns(preview: SelectionPreview | None) -> dict:
    if preview is None:
        return {}
    data = selection_preview_to_dict(preview)
    return {
        "recommended_json": json.dumps(data["recommended"]) if data["recommended"] is not None else None,
        "stage1_profile_json": json.dumps(data["stage1_profile"]),
        "fit_levels_json": json.dumps({r["family_id"]: r["fit"] for r in data["ranked"]}),
        "selection_scores_json": json.dumps(data["scores"]),
        "selection_filter_provider": data["stage1_provider"],
        "selection_judgment_provider": data["stage2_provider"],
        "selection_filter_skipped": data["stage1_skipped"],
        "selection_judgment_skipped": data["stage2_skipped"],
        "selection_skip_reason": data["skip_reason"],
    }


class SelectionConflict(Exception):
    """HTTP 409 — auto selection is not decidable; carries the preview for the client."""

    def __init__(self, preview: SelectionPreview) -> None:
        super().__init__("auto selection is not decidable; choose a strategy")
        self.preview = preview


class ConflictError(Exception):
    """HTTP 409 — suggestion action incompatible with current task status."""
