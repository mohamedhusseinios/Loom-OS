"""Two-stage pattern selection pipeline (daemon side).

Stage 1 infers a ``TaskProfile`` through ``relevance.judge`` (pack ``pattern_stage1``).
Stage 2 scores prefiltered families through ``judgment.judge`` (pack ``pattern_stage2``).
Provider failures never raise: the result falls back to ReAct with ``skip_reason`` set.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from coding_agent.patterns import PatternDoc, PatternRegistry
from coding_agent.selection import FitLevel, RankedStrategy, StrategyCandidate, TaskProfile, autonomy_decidable, fit_level_from_score, prefilter_families, rank_strategies
from daemon.decision import DecisionClient, DecisionResult

logger = logging.getLogger("loom.pattern_selection")

STAGE1_PACK = "pattern_stage1"
STAGE2_PACK = "pattern_stage2"
FALLBACK_FAMILY_ID = "react"
FALLBACK_WHY = "selection_fallback"
DEFAULT_PROFILE = TaskProfile(type="feature", size="med", risk="med", has_tests=False, repo_familiarity="unknown")

# Profile dimension -> allowed labels. Candidate ids are ``<dimension>:<label>``.
_PROFILE_LABELS: dict[str, tuple[str, ...]] = {
    "type": ("feature", "bugfix", "refactor", "test", "docs", "research"),
    "size": ("small", "med", "large"),
    "risk": ("low", "med", "high"),
    "has_tests": ("yes", "no"),
    "repo_familiarity": ("low", "med", "high", "unknown"),
}


@dataclass
class SelectionPreview:
    ranked: list[RankedStrategy] = field(default_factory=list)
    auto_decidable: bool = False
    fallback: bool = False
    stage1_profile: TaskProfile = DEFAULT_PROFILE
    recommended: RankedStrategy | None = None
    scores: dict[str, float] = field(default_factory=dict)
    skip_reason: str | None = None
    provider: str = "none"
    model: str = ""
    stage1_provider: str = "none"
    stage1_model: str = ""
    stage1_skipped: bool = False
    stage1_skip_reason: str | None = None
    stage2_provider: str = "none"
    stage2_model: str = ""
    stage2_skipped: bool = False
    stage2_skip_reason: str | None = None
    latency_ms: float = 0.0

    @property
    def top3(self) -> list[RankedStrategy]:
        return self.ranked[:3]


def _error_result() -> DecisionResult:
    return DecisionResult(provider="none", model="", skipped=True, skip_reason="error")


async def _call_judge(client: DecisionClient, **kwargs: Any) -> DecisionResult:
    try:
        result = await asyncio.to_thread(client.judge, **kwargs)
    except Exception:
        logger.warning("pattern selection judge call failed; treating as skipped", exc_info=True)
        return _error_result()
    if not isinstance(result, DecisionResult):
        logger.warning("pattern selection judge returned %s; treating as bad_payload", type(result).__name__)
        return DecisionResult(skipped=True, skip_reason="bad_payload")
    return result


def _profile_candidates() -> list[dict]:
    return [{"id": f"{dim}:{label}", "label": f"{dim} = {label}"} for dim, labels in _PROFILE_LABELS.items() for label in labels]


def _profile_from_scores(scores: dict[str, float]) -> TaskProfile | None:
    picked: dict[str, str] = {}
    for dim, labels in _PROFILE_LABELS.items():
        best_label: str | None = None
        best_score = -1.0
        for label in labels:
            score = scores.get(f"{dim}:{label}")
            if isinstance(score, (int, float)) and not isinstance(score, bool) and score > best_score:
                best_label, best_score = label, float(score)
        if best_label is not None:
            picked[dim] = best_label
    if not picked:
        return None
    base = DEFAULT_PROFILE
    return TaskProfile(
        type=picked.get("type", base.type),
        size=picked.get("size", base.size),
        risk=picked.get("risk", base.risk),
        has_tests=(picked["has_tests"] == "yes") if "has_tests" in picked else base.has_tests,
        repo_familiarity=picked.get("repo_familiarity", base.repo_familiarity),
    )


def _task_view(task_instruction: str, acceptance_criteria: str) -> dict[str, str]:
    return {"title": "", "instruction": f"{task_instruction}\n\nAcceptance criteria:\n{acceptance_criteria}".strip(), "status": ""}


def _catalog(candidates: list[StrategyCandidate]) -> list[dict]:
    return [{"id": c.family_id, "name": c.doc.name, "when_to_use": list(c.doc.when_to_use), "anti_criteria": list(c.doc.anti_criteria)} for c in candidates]


def _fallback_ranked(registry: PatternRegistry) -> list[RankedStrategy]:
    doc = _react_doc(registry)
    if doc is None:
        return []
    return [RankedStrategy(family_id=doc.id, modifier_ids=[], fit="High", why=[FALLBACK_WHY], expected_cost_class=doc.expected_cost_class, name=doc.name)]


def _react_doc(registry: PatternRegistry) -> PatternDoc | None:
    try:
        doc = registry.get(FALLBACK_FAMILY_ID)
    except KeyError:
        return None
    return doc if doc.status == "active" else None


def _finish(preview: SelectionPreview, ranked: list[RankedStrategy], *, min_fit: FitLevel, require_margin: bool) -> SelectionPreview:
    preview.ranked = ranked
    preview.recommended = ranked[0] if ranked else None
    preview.auto_decidable = autonomy_decidable(ranked, min_fit=min_fit, require_margin=require_margin)
    return preview


async def preview_strategies(*, task_instruction: str, acceptance_criteria: str, registry: PatternRegistry, relevance: DecisionClient, judgment: DecisionClient, available_capabilities: set[str], autonomy_min_fit: FitLevel = "High", autonomy_require_margin: bool = True, stage2_max: int = 5) -> SelectionPreview:
    preview = SelectionPreview()
    task = _task_view(task_instruction, acceptance_criteria)
    profile_candidates = _profile_candidates()

    def fall_back(reason: str | None) -> SelectionPreview:
        preview.fallback = True
        preview.skip_reason = reason or "error"
        return _finish(preview, _fallback_ranked(registry), min_fit=autonomy_min_fit, require_margin=autonomy_require_margin)

    # Stage 1: task profile
    stage1 = await _call_judge(relevance, pack=STAGE1_PACK, task=task, catalog=profile_candidates, candidates=profile_candidates)
    preview.stage1_provider, preview.stage1_model = stage1.provider, stage1.model
    preview.latency_ms += stage1.latency_ms
    profile = None if stage1.skipped else _profile_from_scores(stage1.scores)
    if profile is None:
        preview.stage1_skipped = True
        preview.stage1_skip_reason = (stage1.skip_reason or "error") if stage1.skipped else "bad_payload"
        preview.stage1_profile = DEFAULT_PROFILE
        preview.provider, preview.model = stage1.provider, stage1.model
        return fall_back(preview.stage1_skip_reason)
    preview.stage1_profile = profile

    # Prefilter
    limit = max(1, stage2_max)
    candidates = prefilter_families(registry.active_families(), profile=profile, available_capabilities=available_capabilities, limit=limit)
    if not candidates:
        react = _react_doc(registry)
        if react is not None:
            candidates = [StrategyCandidate(family_id=react.id, modifier_ids=[], doc=react)]
    if not candidates:
        preview.stage2_skipped = True
        preview.stage2_skip_reason = "unsupported"
        return fall_back("unsupported")

    # Stage 2: family fit
    catalog = _catalog(candidates)
    stage2 = await _call_judge(judgment, pack=STAGE2_PACK, task=task, catalog=catalog, candidates=catalog)
    preview.stage2_provider, preview.stage2_model = stage2.provider, stage2.model
    preview.provider, preview.model = stage2.provider, stage2.model
    preview.latency_ms += stage2.latency_ms
    scored = [c for c in candidates if isinstance(stage2.scores.get(c.family_id), (int, float)) and not isinstance(stage2.scores.get(c.family_id), bool)]
    if stage2.skipped or not scored:
        preview.stage2_skipped = True
        preview.stage2_skip_reason = (stage2.skip_reason or "error") if stage2.skipped else "bad_payload"
        return fall_back(preview.stage2_skip_reason)

    scores = {c.family_id: float(stage2.scores[c.family_id]) for c in scored}
    preview.scores = scores
    why_by_id = {fid: [f"{fit_level_from_score(score)} fit (score {score:.2f})"] for fid, score in scores.items()}
    ranked = rank_strategies(scored, scores, why_by_id)
    return _finish(preview, ranked, min_fit=autonomy_min_fit, require_margin=autonomy_require_margin)
