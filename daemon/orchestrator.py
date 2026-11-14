"""Orchestration loop: graph → Jev filter → judgments → optional main LLM → suggestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from daemon.jev_client import JevClient, JevError
from daemon.llm_client import LlmClient, LlmError
from daemon.models import AgentTaskRecord, AgentTaskStatus

logger = logging.getLogger("loom.orchestrator")

# Mid-band thresholds: yes >= 0.7, no < 0.3, otherwise uncertain.
NOUL_YES = 0.7
NOUL_NO = 0.3
PACK_CHAR_CAP = 2000
INSTRUCTION_CHAR_CAP = 1000
CHAT_HISTORY_LIMIT = 8
FILTER_CACHE_TTL_SEC = 30.0

# (key -> (monotonic_ts, selected_hits, mid_keys))
_filter_cache: dict[str, tuple[float, list[dict], list[str]]] = {}

# Loom actions allowed per current task status.
LOOM_ACTIONS: dict[str, list[tuple[str, str]]] = {
    AgentTaskStatus.TODO.value: [
        ("loom.move_ready", "Move task to Ready"),
        ("loom.move_blocked", "Move task to Blocked"),
    ],
    AgentTaskStatus.READY.value: [
        ("loom.move_running", "Move task to Running (ready to implement)"),
        ("loom.move_blocked", "Move task to Blocked"),
    ],
    AgentTaskStatus.RUNNING.value: [
        ("loom.move_blocked", "Move task to Blocked"),
        ("loom.move_done", "Mark task Done"),
    ],
    AgentTaskStatus.BLOCKED.value: [
        ("loom.move_ready", "Unblock — move to Ready"),
        ("loom.move_todo", "Move task back to Todo"),
    ],
    AgentTaskStatus.DONE.value: [
        ("loom.move_archived", "Archive task"),
    ],
    AgentTaskStatus.TRIAGE.value: [
        ("loom.move_todo", "Move task to Todo"),
        ("loom.move_ready", "Move task to Ready"),
    ],
}

STATUS_FOR_ACTION = {
    "loom.move_todo": AgentTaskStatus.TODO,
    "loom.move_ready": AgentTaskStatus.READY,
    "loom.move_running": AgentTaskStatus.RUNNING,
    "loom.move_blocked": AgentTaskStatus.BLOCKED,
    "loom.move_done": AgentTaskStatus.DONE,
    "loom.move_archived": AgentTaskStatus.ARCHIVED,
}


@dataclass
class SuggestResult:
    action_id: str
    action_label: str
    confidence: float
    prose: str
    catalog: list[dict] = field(default_factory=list)
    reply: str = ""
    jev_skipped: bool = False
    graph_empty: bool = False
    escalated: bool = False
    jev_input_tokens: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    mid_band_keys: list[str] = field(default_factory=list)
    context_hash: str = ""
    filter_cache_hit: bool = False


@dataclass
class Judgments:
    complete: float = 0.0
    blocked: float = 0.0
    ready_to_implement: float = 0.0
    candidates: list[dict] = field(default_factory=list)


@dataclass
class ActionDecision:
    action_id: str
    action_label: str
    confidence: float
    uncertain: bool
    mid_band_keys: list[str] = field(default_factory=list)


def load_playbook(project_path: str) -> list[dict]:
    path = Path(project_path) / "loom-playbook.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps:
        if isinstance(s, dict) and s.get("id") and s.get("label"):
            out.append({"id": s["id"], "label": s["label"], "when": s.get("when") or []})
    return out


def loom_catalog_for_status(status: str) -> list[dict]:
    return [{"id": aid, "label": label, "source": "loom"} for aid, label in LOOM_ACTIONS.get(status, [])]


def playbook_for_status(steps: list[dict], status: str) -> list[dict]:
    out = []
    for s in steps:
        when = s.get("when") or []
        if when and status not in when:
            continue
        out.append({"id": s["id"], "label": s["label"], "source": "playbook"})
    return out


def merge_catalog(loom: list[dict], playbook: list[dict], candidates: list[dict]) -> list[dict]:
    """Dedupe by id; drop candidates without a graph citation."""
    seen: set[str] = set()
    merged: list[dict] = []
    for item in loom + playbook:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        merged.append(item)
    for c in candidates:
        cid = c.get("id")
        if not cid or cid in seen:
            continue
        if not c.get("graph_ids"):
            continue
        seen.add(cid)
        merged.append({
            "id": cid,
            "label": c.get("label") or cid,
            "source": "llm",
            "graph_ids": c.get("graph_ids") or [],
        })
    return merged


def _node_snippet(hit: dict, limit: int = 160) -> str:
    nid = hit.get("id") or hit.get("name") or "?"
    label = hit.get("label") or hit.get("text") or hit.get("type") or ""
    return f"{nid}: {label}"[:limit]


def _clip(text: str | None, limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


def _node_id(hit: dict) -> str:
    return str(hit.get("id") or hit.get("name") or "")


def context_hash(task: AgentTaskRecord, hits: list[dict] | None) -> str:
    """Stable hash of task text + the graph node id set used for retrieval."""
    nodes = sorted(_node_id(h) for h in (hits or [])[:12])
    payload = {
        "task_id": task.id,
        "title": task.title,
        "instruction": task.instruction,
        "status": getattr(task.status, "value", task.status),
        "nodes": nodes,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_context_pack(hits: list[dict], max_chars: int = PACK_CHAR_CAP) -> str:
    """Join kept-node snippets, stopping at ``max_chars``."""
    parts: list[str] = []
    used = 0
    for hit in hits:
        snippet = _node_snippet(hit)
        extra = len(snippet) + (1 if parts else 0)
        if parts and used + extra > max_chars:
            break
        if not parts and len(snippet) > max_chars:
            parts.append(_clip(snippet, max_chars))
            break
        parts.append(snippet)
        used += extra
    return "\n".join(parts) or "(no graph hits)"


def clear_filter_cache() -> None:
    _filter_cache.clear()


def _filter_cache_get(key: str) -> tuple[list[dict], list[str]] | None:
    entry = _filter_cache.get(key)
    if entry is None:
        return None
    ts, selected, mid_keys = entry
    if time.monotonic() - ts > FILTER_CACHE_TTL_SEC:
        _filter_cache.pop(key, None)
        return None
    return selected, mid_keys


def _filter_cache_put(key: str, selected: list[dict], mid_keys: list[str]) -> None:
    _filter_cache[key] = (time.monotonic(), selected, mid_keys)


def noul_value(ans: Any) -> float:
    """Extract a noul / probability from a Jev answer object."""
    if not isinstance(ans, dict):
        return 0.0
    if ans.get("type") == "noul" or "noul" in ans:
        try:
            return float(ans.get("noul") or 0)
        except (TypeError, ValueError):
            return 0.0
    if ans.get("type") == "choice":
        probs = ans.get("probabilities") or {}
        choice = ans.get("choice")
        if choice is not None and choice in probs:
            try:
                return float(probs[choice])
            except (TypeError, ValueError):
                return 0.0
    try:
        return float(ans.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def usage_input_tokens(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("input_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def llm_usage_tokens(usage: Any) -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) from an OpenAI-style usage object."""
    if not isinstance(usage, dict):
        return 0, 0

    def _int(key: str, *alts: str) -> int:
        for k in (key, *alts):
            if k in usage and usage[k] is not None:
                try:
                    return int(usage[k])
                except (TypeError, ValueError):
                    continue
        return 0

    return _int("prompt_tokens", "input_tokens"), _int("completion_tokens", "output_tokens")


def _band(value: float) -> str:
    if value >= NOUL_YES:
        return "yes"
    if value < NOUL_NO:
        return "no"
    return "mid"


def partition_relevance(
    scored: list[tuple[float, dict]],
    yes_threshold: float = NOUL_YES,
    no_threshold: float = NOUL_NO,
    keep_yes: int = 6,
    keep_mid: int = 6,
    fallback: int = 4,
) -> tuple[list[dict], list[dict], list[str]]:
    """Split scored hits into relevant (>= yes) and mid-band; fallback if none remain."""
    yes_hits = [(s, h) for s, h in scored if s >= yes_threshold]
    mid_hits = [(s, h) for s, h in scored if no_threshold <= s < yes_threshold]
    yes_hits.sort(key=lambda x: x[0], reverse=True)
    mid_hits.sort(key=lambda x: x[0], reverse=True)
    mid_keys = [f"rel:{_node_snippet(h)}" for s, h in mid_hits[:keep_mid]]
    if not yes_hits and not mid_hits:
        fallback_hits = [h for _, h in scored[:fallback]]
        return fallback_hits, [], []
    selected = [h for _, h in yes_hits[:keep_yes]] + [h for _, h in mid_hits[:keep_mid]]
    return selected, [h for _, h in mid_hits[:keep_mid]], mid_keys


def map_judgments_to_action(
    status: str,
    judgments: Judgments,
    catalog: list[dict],
) -> ActionDecision:
    """Map atomic Jev judgments onto a catalog action. Confidence is a real noul."""
    if not catalog:
        return ActionDecision(
            "loom.move_ready", "Move task to Ready", 0.5, True, ["empty_catalog"],
        )
    by_id = {c["id"]: c for c in catalog}
    mid_keys = [
        name for name, val in (
            ("complete", judgments.complete),
            ("blocked", judgments.blocked),
            ("ready_to_implement", judgments.ready_to_implement),
        )
        if _band(val) == "mid"
    ]
    uncertain = bool(mid_keys)

    def pick(action_id: str, confidence: float, force_uncertain: bool | None = None) -> ActionDecision | None:
        item = by_id.get(action_id)
        if item is None:
            return None
        flag = uncertain if force_uncertain is None else (force_uncertain or uncertain)
        if confidence < NOUL_YES:
            flag = True
        return ActionDecision(action_id, item["label"], float(confidence), flag, mid_keys)

    grounded = [
        c for c in judgments.candidates
        if (c.get("noul") or 0) >= NOUL_YES and c.get("id") in by_id
    ]

    def fallback(force_uncertain: bool = True) -> ActionDecision:
        if grounded:
            best = max(grounded, key=lambda c: c.get("noul") or 0)
            chosen = pick(best["id"], best["noul"], force_uncertain=force_uncertain or uncertain)
            if chosen is not None:
                return chosen
        first = catalog[0]
        conf = max(judgments.complete, judgments.blocked, judgments.ready_to_implement, 0.0)
        return ActionDecision(
            first["id"], first["label"], conf if conf else 0.5,
            True if force_uncertain else uncertain, mid_keys,
        )

    blocked, ready, complete = judgments.blocked, judgments.ready_to_implement, judgments.complete

    if status == AgentTaskStatus.TODO.value:
        if _band(blocked) == "yes":
            return pick("loom.move_blocked", blocked) or fallback()
        if _band(ready) == "yes":
            return pick("loom.move_ready", ready) or fallback()
        if _band(blocked) == "mid" and blocked >= ready:
            return pick("loom.move_blocked", blocked, True) or fallback()
        if _band(ready) == "mid":
            return pick("loom.move_ready", ready, True) or fallback()
        return fallback()

    if status == AgentTaskStatus.READY.value:
        if _band(blocked) == "yes":
            return pick("loom.move_blocked", blocked) or fallback()
        if _band(ready) == "yes":
            return pick("loom.move_running", ready) or fallback()
        if _band(blocked) == "mid" and blocked >= ready:
            return pick("loom.move_blocked", blocked, True) or fallback()
        if _band(ready) == "mid":
            return pick("loom.move_running", ready, True) or fallback()
        return fallback()

    if status == AgentTaskStatus.RUNNING.value:
        if _band(blocked) == "yes":
            return pick("loom.move_blocked", blocked) or fallback()
        if _band(complete) == "yes":
            return pick("loom.move_done", complete) or fallback()
        if _band(blocked) == "mid" and blocked >= complete:
            return pick("loom.move_blocked", blocked, True) or fallback()
        if _band(complete) == "mid":
            return pick("loom.move_done", complete, True) or fallback()
        return fallback()

    if status == AgentTaskStatus.BLOCKED.value:
        if _band(blocked) == "yes":
            return fallback(force_uncertain=True)
        if _band(blocked) == "no" and _band(ready) == "yes":
            return pick("loom.move_ready", ready) or fallback()
        if _band(blocked) == "no" and "loom.move_todo" in by_id:
            # Not-blocked noul is the complement of the blocked question.
            conf = (1.0 - blocked) if _band(ready) == "no" else ready
            return pick("loom.move_todo", conf) or fallback()
        if _band(blocked) == "mid":
            if ready >= blocked:
                return pick("loom.move_ready", ready, True) or fallback()
            return fallback(force_uncertain=True)
        return fallback()

    if status == AgentTaskStatus.DONE.value:
        conf = complete if complete else 0.5
        return pick("loom.move_archived", conf, _band(complete) != "yes") or fallback()

    if status == AgentTaskStatus.TRIAGE.value:
        if _band(ready) == "yes":
            return pick("loom.move_ready", ready) or fallback()
        if "loom.move_todo" in by_id:
            conf = (1.0 - ready) if _band(ready) == "no" else ready
            return pick("loom.move_todo", conf) or fallback()
        return fallback()

    return fallback()


def template_reply(action_label: str) -> str:
    return f"Suggested next step: {action_label}"


def _answers_of(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    answers = payload.get("answers")
    return answers if isinstance(answers, dict) else {}


class Orchestrator:
    """Runs one suggest/chat cycle against graph memory + Jev + main LLM."""

    def __init__(self, graph_engine, jev: JevClient | None = None, llm: LlmClient | None = None):
        self.graph_engine = graph_engine
        self.jev = jev or JevClient()
        self.llm = llm or LlmClient()

    async def run_suggest_cycle(
        self,
        project_path: str,
        project: str,
        task: AgentTaskRecord,
        chat_messages: list[dict[str, str]] | None = None,
        user_message: str | None = None,
        model: str | None = None,
        prefetched_hits: list[dict] | None = None,
        always_llm: bool = False,
    ) -> SuggestResult:
        question = f"{task.title}\n{task.instruction}"
        if user_message:
            question = f"{question}\n{user_message}"

        if prefetched_hits is not None:
            hits = list(prefetched_hits)
        else:
            hits = await self._retrieve(project_path, project, question)
        ctx_hash = context_hash(task, hits)
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not hits and not graph_path.exists():
            return SuggestResult(
                action_id="loom.refresh_graph",
                action_label="Build or refresh the project graph",
                confidence=1.0,
                prose="No graph memory found for this project. Build the knowledge graph first, then ask again.",
                catalog=[{"id": "loom.refresh_graph", "label": "Build or refresh the project graph", "source": "loom"}],
                reply="I don't have graph memory for this project yet. Please build/refresh the graph, then we can plan the next step.",
                graph_empty=True,
                context_hash=ctx_hash,
            )

        jev_skipped = False
        jev_input_tokens = 0
        mid_from_filter: list[str] = []
        filter_cache_hit = False
        filtered = hits[:8]
        if hits and self.jev.available:
            cached = _filter_cache_get(ctx_hash)
            if cached is not None:
                filtered, mid_from_filter = cached
                filter_cache_hit = True
            else:
                try:
                    filtered, mid_from_filter, used = await asyncio.to_thread(
                        self._jev_filter, hits, task,
                    )
                    jev_input_tokens += used
                    _filter_cache_put(ctx_hash, filtered, mid_from_filter)
                except JevError:
                    logger.warning("Jev filter failed; using top hybrid hits", exc_info=True)
                    jev_skipped = True
                    filtered = hits[:5]
        elif hits:
            jev_skipped = True

        pack = build_context_pack(filtered)
        playbook = load_playbook(project_path)
        loom = loom_catalog_for_status(task.status.value)
        pb = playbook_for_status(playbook, task.status.value)

        reply = ""
        candidates: list[dict] = []
        llm_prompt_tokens = 0
        llm_completion_tokens = 0

        async def _propose() -> None:
            nonlocal reply, candidates, llm_prompt_tokens, llm_completion_tokens
            if self.llm.available:
                try:
                    reply, candidates = await asyncio.to_thread(
                        self._llm_propose, pack, task, chat_messages, user_message, model,
                    )
                    llm_prompt_tokens, llm_completion_tokens = llm_usage_tokens(
                        getattr(self.llm, "last_usage", None)
                    )
                except LlmError as e:
                    reply = f"(Main model unavailable: {e})"
            else:
                reply = "Add a DeepSeek (or other) API key in Agent settings to enable chat."

        # Chat with a user message always calls the main LLM first so Jev can
        # also score whether proposed candidates are grounded in cited nodes.
        if user_message or always_llm:
            await _propose()

        catalog = merge_catalog(loom, pb, candidates)
        if not catalog:
            catalog = loom or [{"id": "loom.move_ready", "label": "Move task to Ready", "source": "loom"}]

        decision = ActionDecision(catalog[0]["id"], catalog[0]["label"], 0.5, True, [])
        judgments = Judgments()
        if self.jev.available and not jev_skipped:
            try:
                decision, judgments, used = await asyncio.to_thread(
                    self._jev_judge, pack, task, catalog, candidates,
                )
                jev_input_tokens += used
            except JevError:
                logger.warning("Jev judgments failed; using first catalog option", exc_info=True)
                jev_skipped = True

        mid_band_keys = list(dict.fromkeys(list(decision.mid_band_keys) + mid_from_filter))
        escalated = (
            jev_skipped
            or decision.uncertain
            or decision.confidence < NOUL_YES
            or any(_band(v) == "mid" for v in (
                judgments.complete, judgments.blocked, judgments.ready_to_implement,
            ))
        )

        # Auto-suggest: call DeepSeek only when Jev is uncertain or skipped.
        # always_llm (benchmark baseline) already proposed above.
        if not user_message and not always_llm and escalated:
            await _propose()
            if candidates:
                catalog = merge_catalog(loom, pb, candidates)
                if not catalog:
                    catalog = loom or [{"id": "loom.move_ready", "label": "Move task to Ready", "source": "loom"}]
                if self.jev.available and not jev_skipped:
                    try:
                        grounded, used = await asyncio.to_thread(
                            self._jev_ground_candidates, pack, task, candidates,
                        )
                        jev_input_tokens += used
                        judgments.candidates = grounded
                        decision = map_judgments_to_action(
                            task.status.value, judgments, catalog,
                        )
                    except JevError:
                        logger.warning(
                            "Jev grounding pass failed; keeping prior decision",
                            exc_info=True,
                        )
                for item in catalog:
                    if item["id"] == decision.action_id:
                        decision.action_label = item["label"]
                        break

        if not reply:
            reply = template_reply(decision.action_label)

        logger.info(
            "orchestrator cycle project=%s task=%s action=%s confidence=%.3f "
            "jev_input_tokens=%s llm_prompt_tokens=%s llm_completion_tokens=%s "
            "jev_skipped=%s escalated=%s mid_band=%s",
            project, task.id, decision.action_id, decision.confidence,
            jev_input_tokens, llm_prompt_tokens, llm_completion_tokens,
            jev_skipped, escalated, ",".join(mid_band_keys) or "-",
        )

        return SuggestResult(
            action_id=decision.action_id,
            action_label=decision.action_label,
            confidence=decision.confidence,
            prose=reply,
            catalog=catalog,
            reply=reply,
            jev_skipped=jev_skipped,
            escalated=escalated,
            jev_input_tokens=jev_input_tokens,
            llm_prompt_tokens=llm_prompt_tokens,
            llm_completion_tokens=llm_completion_tokens,
            mid_band_keys=mid_band_keys,
            context_hash=ctx_hash,
            filter_cache_hit=filter_cache_hit,
        )

    async def _retrieve(self, project_path: str, project: str, question: str) -> list[dict]:
        if self.graph_engine is None:
            return []
        try:
            return await self.graph_engine.hybrid_query(project_path, project, question, top_k=12)
        except Exception:
            logger.warning("hybrid_query failed", exc_info=True)
            return []

    def _jev_filter(
        self, hits: list[dict], task: AgentTaskRecord,
    ) -> tuple[list[dict], list[str], int]:
        questions: dict[str, dict] = {}
        for i, h in enumerate(hits[:12]):
            nid = h.get("id") or h.get("name") or f"hit-{i}"
            questions[f"rel_{i}"] = {
                "type": "noul",
                "instructions": (
                    f"Is graph node `{nid}` relevant to the task described in `task`?"
                ),
                "criteria": {
                    "true": "The node is needed to understand or implement the task.",
                    "false": "The node is unrelated to the task.",
                },
            }
        state = {
            "task": {"title": task.title, "instruction": task.instruction, "status": task.status.value},
            "nodes": [_node_snippet(h) for h in hits[:12]],
        }
        payload = self.jev.ask(state, questions)
        answers = _answers_of(payload)
        scored: list[tuple[float, dict]] = []
        for i, h in enumerate(hits[:12]):
            scored.append((noul_value(answers.get(f"rel_{i}") or {}), h))
        scored.sort(key=lambda x: x[0], reverse=True)
        selected, _mid, mid_keys = partition_relevance(scored)
        return selected, mid_keys, usage_input_tokens(payload)

    def _llm_propose(
        self,
        pack: str,
        task: AgentTaskRecord,
        chat_messages: list[dict[str, str]] | None,
        user_message: str | None,
        model: str | None,
    ) -> tuple[str, list[dict]]:
        system = (
            "You are the Loom agent. Use ONLY the provided graph context. "
            "Respond with JSON: {\"reply\": \"human language\", "
            "\"candidates\": [{\"id\": \"custom.step\", \"label\": \"...\", \"graph_ids\": [\"node-id\"]}]}. "
            "Candidates without graph_ids are invalid. Keep reply to 2-4 sentences."
        )
        messages = [{"role": "system", "content": system}]
        if chat_messages:
            messages.extend(chat_messages[-CHAT_HISTORY_LIMIT:])
        user = (
            f"Task status={task.status.value}\nTitle: {_clip(task.title, 300)}\n"
            f"Instruction: {_clip(task.instruction, INSTRUCTION_CHAR_CAP)}\n\n"
            f"Graph context:\n{pack}"
        )
        if user_message:
            user += f"\n\nUser message: {user_message}"
        messages.append({"role": "user", "content": user})
        data = self.llm.chat_json(messages, model=model or "deepseek-chat")
        reply = data.get("reply") or ""
        candidates = data.get("candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        return reply, [c for c in candidates if isinstance(c, dict)]

    def _jev_judge(
        self,
        pack: str,
        task: AgentTaskRecord,
        catalog: list[dict],
        candidates: list[dict],
    ) -> tuple[ActionDecision, Judgments, int]:
        state = {
            "task": {
                "title": task.title,
                "instruction": task.instruction,
                "status": task.status.value,
            },
            "graph": pack,
            "catalog": {c["id"]: c["label"] for c in catalog},
        }
        questions: dict[str, dict] = {
            "complete": {
                "type": "noul",
                "instructions": "Is the work on this task already complete?",
                "criteria": {
                    "true": "The graph context and task description show the work is finished.",
                    "false": "The work is not finished, or there is not enough evidence it is done.",
                },
            },
            "blocked": {
                "type": "noul",
                "instructions": "Is this task blocked?",
                "criteria": {
                    "true": "The task cannot proceed because of a missing dependency, decision, or obstacle.",
                    "false": "The task can proceed.",
                },
            },
            "ready_to_implement": {
                "type": "noul",
                "instructions": "Is this task ready to implement?",
                "criteria": {
                    "true": "The task is clear enough to start implementation now.",
                    "false": "The task still needs planning, unblocking, or more definition.",
                },
            },
        }
        cited = [c for c in candidates if c.get("id") and c.get("graph_ids")]
        for i, c in enumerate(cited):
            nid = ", ".join(str(g) for g in (c.get("graph_ids") or [])[:4])
            questions[f"grounded_{i}"] = {
                "type": "noul",
                "instructions": (
                    f"Is proposed step `{c['id']}` ({c.get('label') or c['id']}) "
                    f"grounded in the cited graph node(s) `{nid}`?"
                ),
                "criteria": {
                    "true": "The cited graph node actually supports this step.",
                    "false": "The citation is missing, unrelated, or does not support the step.",
                },
            }
        payload = self.jev.ask(state, questions)
        answers = _answers_of(payload)
        grounded_cands = []
        for i, c in enumerate(cited):
            grounded_cands.append({
                "id": c["id"],
                "label": c.get("label") or c["id"],
                "noul": noul_value(answers.get(f"grounded_{i}") or {}),
            })
        judgments = Judgments(
            complete=noul_value(answers.get("complete") or {}),
            blocked=noul_value(answers.get("blocked") or {}),
            ready_to_implement=noul_value(answers.get("ready_to_implement") or {}),
            candidates=grounded_cands,
        )
        decision = map_judgments_to_action(task.status.value, judgments, catalog)
        return decision, judgments, usage_input_tokens(payload)

    def _jev_ground_candidates(
        self,
        pack: str,
        task: AgentTaskRecord,
        candidates: list[dict],
    ) -> tuple[list[dict], int]:
        """Score cited LLM candidates with noul questions only (no complete/blocked/ready)."""
        cited = [c for c in candidates if c.get("id") and c.get("graph_ids")]
        if not cited:
            return [], 0
        questions: dict[str, dict] = {}
        for i, c in enumerate(cited):
            nid = ", ".join(str(g) for g in (c.get("graph_ids") or [])[:4])
            questions[f"grounded_{i}"] = {
                "type": "noul",
                "instructions": (
                    f"Is proposed step `{c['id']}` ({c.get('label') or c['id']}) "
                    f"grounded in the cited graph node(s) `{nid}`?"
                ),
                "criteria": {
                    "true": "The cited graph node actually supports this step.",
                    "false": "The citation is missing, unrelated, or does not support the step.",
                },
            }
        state = {
            "task": {
                "title": task.title,
                "instruction": task.instruction,
                "status": task.status.value,
            },
            "graph": pack,
        }
        payload = self.jev.ask(state, questions)
        answers = _answers_of(payload)
        grounded = []
        for i, c in enumerate(cited):
            grounded.append({
                "id": c["id"],
                "label": c.get("label") or c["id"],
                "noul": noul_value(answers.get(f"grounded_{i}") or {}),
            })
        return grounded, usage_input_tokens(payload)
