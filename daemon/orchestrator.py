"""Orchestration loop: graph → decision filter → judgments → optional main LLM → suggestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from daemon.decision import DecisionClient, DecisionConfig, DecisionResult, ProviderId, build_decision_clients, effective_thresholds, resolve_decision_config
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
FILTER_SKIP_TOP_HITS = 5

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
    filter_provider: str = ""
    filter_model: str = ""
    judgment_provider: str = ""
    judgment_model: str = ""
    filter_skipped: bool = False
    judgment_skipped: bool = False
    filter_skip_reason: str | None = None
    judgment_skip_reason: str | None = None
    filter_input_tokens: int | None = None
    judgment_input_tokens: int | None = None
    filter_latency_ms: float | None = None
    judgment_latency_ms: float | None = None
    effective_thresholds_json: str = ""


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


def _band(value: float, yes: float = NOUL_YES, no: float = NOUL_NO) -> str:
    if value >= yes:
        return "yes"
    if value < no:
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


def map_judgments_to_action(status: str, judgments: Judgments, catalog: list[dict], yes_threshold: float = NOUL_YES, no_threshold: float = NOUL_NO) -> ActionDecision:
    """Map atomic decision judgments onto a catalog action. Confidence is a real noul."""
    def band(value: float) -> str:
        return _band(value, yes_threshold, no_threshold)

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
        if band(val) == "mid"
    ]
    uncertain = bool(mid_keys)

    def pick(action_id: str, confidence: float, force_uncertain: bool | None = None) -> ActionDecision | None:
        item = by_id.get(action_id)
        if item is None:
            return None
        flag = uncertain if force_uncertain is None else (force_uncertain or uncertain)
        if confidence < yes_threshold:
            flag = True
        return ActionDecision(action_id, item["label"], float(confidence), flag, mid_keys)

    grounded = [
        c for c in judgments.candidates
        if (c.get("noul") or 0) >= yes_threshold and c.get("id") in by_id
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
        if band(blocked) == "yes":
            return pick("loom.move_blocked", blocked) or fallback()
        if band(ready) == "yes":
            return pick("loom.move_ready", ready) or fallback()
        if band(blocked) == "mid" and blocked >= ready:
            return pick("loom.move_blocked", blocked, True) or fallback()
        if band(ready) == "mid":
            return pick("loom.move_ready", ready, True) or fallback()
        return fallback()

    if status == AgentTaskStatus.READY.value:
        if band(blocked) == "yes":
            return pick("loom.move_blocked", blocked) or fallback()
        if band(ready) == "yes":
            return pick("loom.move_running", ready) or fallback()
        if band(blocked) == "mid" and blocked >= ready:
            return pick("loom.move_blocked", blocked, True) or fallback()
        if band(ready) == "mid":
            return pick("loom.move_running", ready, True) or fallback()
        return fallback()

    if status == AgentTaskStatus.RUNNING.value:
        if band(blocked) == "yes":
            return pick("loom.move_blocked", blocked) or fallback()
        if band(complete) == "yes":
            return pick("loom.move_done", complete) or fallback()
        if band(blocked) == "mid" and blocked >= complete:
            return pick("loom.move_blocked", blocked, True) or fallback()
        if band(complete) == "mid":
            return pick("loom.move_done", complete, True) or fallback()
        return fallback()

    if status == AgentTaskStatus.BLOCKED.value:
        if band(blocked) == "yes":
            return fallback(force_uncertain=True)
        if band(blocked) == "no" and band(ready) == "yes":
            return pick("loom.move_ready", ready) or fallback()
        if band(blocked) == "no" and "loom.move_todo" in by_id:
            # Not-blocked noul is the complement of the blocked question.
            conf = (1.0 - blocked) if band(ready) == "no" else ready
            return pick("loom.move_todo", conf) or fallback()
        if band(blocked) == "mid":
            if ready >= blocked:
                return pick("loom.move_ready", ready, True) or fallback()
            return fallback(force_uncertain=True)
        return fallback()

    if status == AgentTaskStatus.DONE.value:
        conf = complete if complete else 0.5
        return pick("loom.move_archived", conf, band(complete) != "yes") or fallback()

    if status == AgentTaskStatus.TRIAGE.value:
        if band(ready) == "yes":
            return pick("loom.move_ready", ready) or fallback()
        if "loom.move_todo" in by_id:
            conf = (1.0 - ready) if band(ready) == "no" else ready
            return pick("loom.move_todo", conf) or fallback()
        return fallback()

    return fallback()


def template_reply(action_label: str) -> str:
    return f"Suggested next step: {action_label}"


def filter_cache_key(provider: str, model: str, ctx_hash: str, thresholds: Mapping[str, float] | None = None) -> str:
    thr = json.dumps(dict(thresholds or {}), sort_keys=True, separators=(",", ":"))
    return f"{provider}\x1f{model}\x1f{ctx_hash}\x1f{thr}"


def _provider_id(value: str) -> ProviderId:
    if value in ("typesafe", "ollama", "gliclass", "none"):
        return cast(ProviderId, value)
    return "none"


def _settings_value(settings: Any, name: str) -> Any:
    if settings is None:
        return None
    if isinstance(settings, Mapping):
        return settings.get(name)
    return getattr(settings, name, None)


def _provider_overrides(settings: Any, provider: str) -> dict[str, Any] | None:
    raw = _settings_value(settings, "threshold_overrides")
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, Mapping):
        return None
    item = raw.get(provider)
    if isinstance(item, Mapping):
        return dict(item)
    return None


def _role_identity(client: Any, config: DecisionConfig | None, role: str) -> tuple[str, str]:
    if config is not None:
        if role == "filter":
            return config.filter_provider, config.filter_model
        return config.judgment_provider, config.judgment_model
    provider = getattr(client, "provider", None) or ""
    model = getattr(client, "model", None) or ""
    return str(provider), str(model)


def _role_thresholds(provider: str, settings: Any, config: DecisionConfig | None, role: str) -> dict[str, float]:
    if config is not None:
        chosen = config.filter_thresholds if role == "filter" else config.judgment_thresholds
        return chosen.as_dict()
    return effective_thresholds(provider or "none", _provider_overrides(settings, provider or "none"))


def _score_or_mid(scores: Mapping[str, Any], key: str, mid: float) -> float:
    if key not in scores:
        return mid
    try:
        return float(scores[key])
    except (TypeError, ValueError):
        return mid


def select_relevant_hits(hits: list[dict], scores: Mapping[str, Any], thresholds: Mapping[str, float]) -> tuple[list[dict], list[str]]:
    """Apply keep / mid / drop. Missing per-hit scores stay in the mid band; unknown keys are ignored."""
    mid = float(thresholds["mid"])
    scored = [(_score_or_mid(scores, f"rel_{index}", mid), hit) for index, hit in enumerate(hits[:12])]
    scored.sort(key=lambda item: item[0], reverse=True)
    selected, _mid_hits, mid_keys = partition_relevance(scored, yes_threshold=float(thresholds["keep"]), no_threshold=float(thresholds["drop"]))
    return selected, mid_keys


def judgments_from_scores(scores: Mapping[str, Any], candidates: list[dict], thresholds: Mapping[str, float]) -> Judgments:
    """Read complete / blocked / ready / grounded only. A missing score is mid-band."""
    mid = float(thresholds["mid"])
    cited = [c for c in candidates if isinstance(c, dict) and c.get("id") and c.get("graph_ids")]
    grounded = [{"id": cand["id"], "label": cand.get("label") or cand["id"], "noul": _score_or_mid(scores, f"grounded_{index}", mid)} for index, cand in enumerate(cited)]
    return Judgments(complete=_score_or_mid(scores, "complete", mid), blocked=_score_or_mid(scores, "blocked", mid), ready_to_implement=_score_or_mid(scores, "ready_to_implement", mid), candidates=grounded)


def _skipped_decision(catalog: list[dict]) -> ActionDecision:
    first = catalog[0]
    return ActionDecision(first["id"], first["label"], 0.5, True, [])


def _apply_judgment(status: str, result: DecisionResult, candidates: list[dict], catalog: list[dict], thresholds: Mapping[str, float]) -> tuple[ActionDecision, Judgments, bool, str | None]:
    if result.skipped:
        return _skipped_decision(catalog), Judgments(), True, result.skip_reason or "error"
    judgments = judgments_from_scores(result.scores, candidates, thresholds)
    decision = map_judgments_to_action(status, judgments, catalog, yes_threshold=float(thresholds["keep"]), no_threshold=float(thresholds["drop"]))
    return decision, judgments, False, None


def _should_escalate(filter_skipped: bool, judgment_skipped: bool, decision: ActionDecision, judgments: Judgments, thresholds: Mapping[str, float]) -> bool:
    keep = float(thresholds["keep"])
    drop = float(thresholds["drop"])
    escalate_at = float(thresholds["escalate"])
    key_mid = any(_band(value, keep, drop) == "mid" for value in (judgments.complete, judgments.blocked, judgments.ready_to_implement))
    return bool(filter_skipped or judgment_skipped or decision.uncertain or decision.confidence < escalate_at or key_mid)


def _merge_tokens(current: int | None, incoming: int | None) -> int | None:
    if incoming is None:
        return current
    if current is None:
        return int(incoming)
    return int(current) + int(incoming)


def _legacy_token_sum(filter_tokens: int | None, judgment_tokens: int | None) -> int:
    total = 0
    if isinstance(filter_tokens, int):
        total += filter_tokens
    if isinstance(judgment_tokens, int):
        total += judgment_tokens
    return total


def _thresholds_json(filter_thresholds: Mapping[str, float], judgment_thresholds: Mapping[str, float]) -> str:
    return json.dumps({"filter": dict(filter_thresholds), "judgment": dict(judgment_thresholds)}, sort_keys=True)


def _error_result(provider: str, model: str) -> DecisionResult:
    return DecisionResult(provider=_provider_id(provider), model=model, skipped=True, skip_reason="error")


class Orchestrator:
    """One suggest/chat cycle: graph, two DecisionClients, optional main LLM."""

    def __init__(self, graph_engine, jev: DecisionClient | None = None, llm: LlmClient | None = None, relevance_client: DecisionClient | None = None, judgment_client: DecisionClient | None = None):
        self.graph_engine = graph_engine
        self.llm = llm or LlmClient()
        if relevance_client is None and judgment_client is None and jev is None:
            self._injected: tuple[DecisionClient, DecisionClient] | None = None
        else:
            relevance = relevance_client if relevance_client is not None else jev
            judgment = judgment_client if judgment_client is not None else jev
            if relevance is None:
                relevance = judgment
            if judgment is None:
                judgment = relevance
            assert relevance is not None and judgment is not None
            self._injected = (relevance, judgment)

    def _open_clients(self, settings: Any, raw_keys: Mapping[str, str] | None) -> tuple[DecisionClient | None, DecisionClient | None, DecisionConfig | None]:
        if self._injected is not None:
            return self._injected[0], self._injected[1], None
        try:
            config = resolve_decision_config(settings, raw_keys)
        except ValueError:
            logger.warning("decision config invalid; skipping filter and judgment", exc_info=True)
            return None, None, None
        relevance, judgment = build_decision_clients(config)
        return relevance, judgment, config

    async def _call_client(self, client: DecisionClient, method: str, **kwargs: Any) -> DecisionResult:
        try:
            return await asyncio.to_thread(getattr(client, method), **kwargs)
        except Exception:
            logger.warning("decision %s failed; treating the call as skipped", method, exc_info=True)
            provider, model = _role_identity(client, None, "filter" if method == "filter_relevance" else "judgment")
            return _error_result(provider, model)

    async def run_suggest_cycle(self, project_path: str, project: str, task: AgentTaskRecord, chat_messages: list[dict[str, str]] | None = None, user_message: str | None = None, model: str | None = None, prefetched_hits: list[dict] | None = None, always_llm: bool = False, settings: Any = None, raw_keys: Mapping[str, str] | None = None) -> SuggestResult:
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

        relevance, judgment, config = self._open_clients(settings, raw_keys)
        filter_provider, filter_model = _role_identity(relevance, config, "filter") if relevance is not None else (str(_settings_value(settings, "filter_provider") or ""), "")
        judgment_provider, judgment_model = _role_identity(judgment, config, "judgment") if judgment is not None else (str(_settings_value(settings, "judgment_provider") or ""), "")
        filter_thresholds = _role_thresholds(filter_provider or "none", settings, config, "filter")
        judgment_thresholds = _role_thresholds(judgment_provider or "none", settings, config, "judgment")
        effective_json = _thresholds_json(filter_thresholds, judgment_thresholds) if relevance is not None or config is not None else ""

        mid_from_filter: list[str] = []
        filter_cache_hit = False
        filter_skipped = False
        filter_skip_reason: str | None = None
        filter_input_tokens: int | None = None
        filter_latency_ms: float | None = None
        filtered = hits[:FILTER_SKIP_TOP_HITS]
        if hits and relevance is None:
            filter_skipped = True
            filter_skip_reason = "error"
        elif hits and relevance is not None:
            cache_key = filter_cache_key(filter_provider, filter_model, ctx_hash, filter_thresholds)
            cached = _filter_cache_get(cache_key)
            if cached is not None:
                filtered, mid_from_filter = cached
                filter_cache_hit = True
            else:
                filter_result = await self._call_client(relevance, "filter_relevance", pack=build_context_pack(hits), task=task, catalog=[], hits=hits)
                filter_provider = filter_result.provider or filter_provider
                filter_model = filter_result.model or filter_model
                filter_input_tokens = filter_result.usage.input_tokens
                filter_latency_ms = filter_result.latency_ms
                if filter_result.skipped:
                    filter_skipped = True
                    filter_skip_reason = filter_result.skip_reason or "error"
                    filtered = hits[:FILTER_SKIP_TOP_HITS]
                else:
                    filtered, mid_from_filter = select_relevant_hits(hits, filter_result.scores, filter_thresholds)
                    _filter_cache_put(cache_key, filtered, mid_from_filter)

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

        # Chat always calls the main model first so judgment can score cited candidates.
        if user_message or always_llm:
            await _propose()

        catalog = merge_catalog(loom, pb, candidates)
        if not catalog:
            catalog = loom or [{"id": "loom.move_ready", "label": "Move task to Ready", "source": "loom"}]

        decision = _skipped_decision(catalog)
        judgments = Judgments()
        judgment_skipped = False
        judgment_skip_reason: str | None = None
        judgment_input_tokens: int | None = None
        judgment_latency_ms: float | None = None
        if judgment is None:
            judgment_skipped = True
            judgment_skip_reason = "error"
        else:
            judgment_result = await self._call_client(judgment, "judge", pack=pack, task=task, catalog=catalog, candidates=candidates)
            judgment_provider = judgment_result.provider or judgment_provider
            judgment_model = judgment_result.model or judgment_model
            judgment_input_tokens = _merge_tokens(judgment_input_tokens, judgment_result.usage.input_tokens)
            judgment_latency_ms = judgment_result.latency_ms
            decision, judgments, judgment_skipped, judgment_skip_reason = _apply_judgment(task.status.value, judgment_result, candidates, catalog, judgment_thresholds)

        escalated = _should_escalate(filter_skipped, judgment_skipped, decision, judgments, judgment_thresholds)

        # Auto-suggest calls DeepSeek when escalation rules fire, then grounds new candidates.
        if not user_message and not always_llm and escalated:
            await _propose()
            if candidates:
                catalog = merge_catalog(loom, pb, candidates)
                if not catalog:
                    catalog = loom or [{"id": "loom.move_ready", "label": "Move task to Ready", "source": "loom"}]
                if judgment is not None:
                    ground = await self._call_client(judgment, "judge", pack=pack, task=task, catalog=catalog, candidates=candidates)
                    judgment_input_tokens = _merge_tokens(judgment_input_tokens, ground.usage.input_tokens)
                    if ground.skipped and not judgment_skipped:
                        logger.warning("judgment grounding pass failed; keeping prior decision")
                    else:
                        judgment_provider = ground.provider or judgment_provider
                        judgment_model = ground.model or judgment_model
                        judgment_latency_ms = ground.latency_ms
                        if ground.skipped:
                            judgment_skipped = True
                            judgment_skip_reason = ground.skip_reason or "error"
                        else:
                            decision, judgments, judgment_skipped, judgment_skip_reason = _apply_judgment(task.status.value, ground, candidates, catalog, judgment_thresholds)
                for item in catalog:
                    if item["id"] == decision.action_id:
                        decision.action_label = item["label"]
                        break

        if not reply:
            reply = template_reply(decision.action_label)

        mid_band_keys = list(dict.fromkeys(list(decision.mid_band_keys) + mid_from_filter))
        jev_skipped = filter_skipped or judgment_skipped
        jev_input_tokens = _legacy_token_sum(filter_input_tokens, judgment_input_tokens)
        logger.info(
            "orchestrator cycle project=%s task=%s action=%s confidence=%.3f filter=%s/%s judgment=%s/%s filter_skipped=%s judgment_skipped=%s escalated=%s",
            project, task.id, decision.action_id, decision.confidence,
            filter_provider or "-", filter_model or "-", judgment_provider or "-", judgment_model or "-",
            filter_skipped, judgment_skipped, escalated,
        )
        return SuggestResult(
            action_id=decision.action_id, action_label=decision.action_label, confidence=decision.confidence,
            prose=reply, catalog=catalog, reply=reply, jev_skipped=jev_skipped, escalated=escalated,
            jev_input_tokens=jev_input_tokens, llm_prompt_tokens=llm_prompt_tokens, llm_completion_tokens=llm_completion_tokens,
            mid_band_keys=mid_band_keys, context_hash=ctx_hash, filter_cache_hit=filter_cache_hit,
            filter_provider=filter_provider, filter_model=filter_model, judgment_provider=judgment_provider, judgment_model=judgment_model,
            filter_skipped=filter_skipped, judgment_skipped=judgment_skipped, filter_skip_reason=filter_skip_reason, judgment_skip_reason=judgment_skip_reason,
            filter_input_tokens=filter_input_tokens, judgment_input_tokens=judgment_input_tokens, filter_latency_ms=filter_latency_ms, judgment_latency_ms=judgment_latency_ms,
            effective_thresholds_json=effective_json,
        )

    async def _retrieve(self, project_path: str, project: str, question: str) -> list[dict]:
        if self.graph_engine is None:
            return []
        try:
            return await self.graph_engine.hybrid_query(project_path, project, question, top_k=12)
        except Exception:
            logger.warning("hybrid_query failed", exc_info=True)
            return []

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
