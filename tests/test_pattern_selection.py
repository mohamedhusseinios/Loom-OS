"""Tests for the daemon two-stage pattern selection pipeline (mock clients, no HTTP)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import coding_agent.patterns as patterns_pkg
from coding_agent.patterns import PatternDoc, PatternRegistry, load_patterns
from daemon.decision import DecisionResult, NullDecisionClient
from daemon.pattern_selection import DEFAULT_PROFILE, SelectionPreview, preview_strategies

_FAMILIES = Path(patterns_pkg.__file__).parent / "families"
_CAPS = {"read_file", "edit", "search", "shell", "git", "read"}

_STAGE1_SCORES = {"type:bugfix": 0.9, "type:feature": 0.2, "size:small": 0.8, "size:med": 0.3, "risk:low": 0.7, "risk:high": 0.1, "has_tests:yes": 0.9, "has_tests:no": 0.1, "repo_familiarity:high": 0.6}


class FakeClient:
    def __init__(self, scores: dict[str, float] | None = None, *, skipped: bool = False, skip_reason: str | None = None, raises: bool = False) -> None:
        self.scores = scores or {}
        self.skipped = skipped
        self.skip_reason = skip_reason
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult:
        raise AssertionError("filter_relevance must not be used")

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult:
        self.calls.append({"pack": pack, "task": task, "catalog": catalog, "candidates": candidates})
        if self.raises:
            raise RuntimeError("boom")
        return DecisionResult(scores=dict(self.scores), provider="typesafe", model="m", skipped=self.skipped, skip_reason=self.skip_reason if self.skipped else None, latency_ms=1.0)


def _registry():
    return load_patterns(_FAMILIES)


async def _run(relevance, judgment, **kwargs) -> SelectionPreview:
    return await preview_strategies(task_instruction="fix the login bug", acceptance_criteria="tests pass", registry=_registry(), relevance=relevance, judgment=judgment, available_capabilities=_CAPS, **kwargs)


async def test_happy_path_ranks_and_top3() -> None:
    relevance = FakeClient(_STAGE1_SCORES)
    judgment = FakeClient({"debug": 0.9, "tdd": 0.6, "react": 0.5, "plan_then_execute": 0.2, "review_only": 0.1})
    preview = await _run(relevance, judgment)
    assert not preview.fallback
    assert preview.skip_reason is None
    assert preview.stage1_profile.type == "bugfix"
    assert preview.stage1_profile.size == "small"
    assert preview.stage1_profile.has_tests is True
    assert [r.family_id for r in preview.ranked] == ["debug", "tdd", "react", "plan_then_execute", "review_only"]
    assert [r.fit for r in preview.ranked] == ["High", "Medium", "Medium", "Low", "Low"]
    assert [r.family_id for r in preview.top3] == ["debug", "tdd", "react"]
    assert preview.recommended is not None and preview.recommended.family_id == "debug"
    assert preview.scores["debug"] == 0.9
    assert preview.provider == "typesafe"
    assert relevance.calls[0]["pack"] == "pattern_stage1"
    assert judgment.calls[0]["pack"] == "pattern_stage2"
    entry = judgment.calls[0]["catalog"][0]
    assert {"id", "when_to_use", "anti_criteria"} <= set(entry)


async def test_planned_family_excluded_from_stage2() -> None:
    judgment = FakeClient({"debug": 0.9, "tdd": 0.5, "react": 0.4, "plan_then_execute": 0.1, "review_only": 0.1, "orchestrator_workers": 0.99})
    preview = await _run(FakeClient(_STAGE1_SCORES), judgment)
    sent = {c["id"] for c in judgment.calls[0]["catalog"]}
    assert not preview.fallback
    assert "orchestrator_workers" not in sent
    assert "orchestrator_workers" not in {r.family_id for r in preview.ranked}


async def test_stage2_max_limits_candidates() -> None:
    judgment = FakeClient({"debug": 0.9, "plan_then_execute": 0.5})
    await _run(FakeClient(_STAGE1_SCORES), judgment, stage2_max=2)
    assert len(judgment.calls[0]["catalog"]) == 2


async def test_stage1_skip_falls_back_to_react() -> None:
    judgment = FakeClient({"debug": 0.9})
    preview = await _run(FakeClient(skipped=True, skip_reason="timeout"), judgment)
    assert preview.fallback
    assert preview.stage1_skipped and preview.stage1_skip_reason == "timeout"
    assert preview.skip_reason == "timeout"
    assert preview.stage1_profile == DEFAULT_PROFILE
    assert [r.family_id for r in preview.ranked] == ["react"]
    assert preview.ranked[0].fit == "High" and preview.ranked[0].why == ["selection_fallback"]
    assert judgment.calls == []


async def test_stage2_skip_falls_back_to_react_keeping_profile() -> None:
    preview = await _run(FakeClient(_STAGE1_SCORES), FakeClient(skipped=True, skip_reason="error"))
    assert preview.fallback and preview.stage2_skipped
    assert preview.stage1_profile.type == "bugfix"
    assert [r.family_id for r in preview.ranked] == ["react"]
    assert preview.ranked[0].why == ["selection_fallback"]


async def test_null_clients_fall_back() -> None:
    preview = await _run(NullDecisionClient(), NullDecisionClient())
    assert preview.fallback
    assert preview.skip_reason == "none"
    assert preview.recommended is not None and preview.recommended.family_id == "react"


async def test_provider_exception_never_raises() -> None:
    preview = await _run(FakeClient(raises=True), FakeClient(raises=True))
    assert preview.fallback and preview.skip_reason == "error"
    preview = await _run(FakeClient(_STAGE1_SCORES), FakeClient(raises=True))
    assert preview.fallback and preview.stage2_skip_reason == "error"


async def test_bad_payload_scores_fall_back() -> None:
    preview = await _run(FakeClient({"unrelated": 0.5}), FakeClient({"debug": 0.9}))
    assert preview.fallback and preview.stage1_skip_reason == "bad_payload"
    preview = await _run(FakeClient(_STAGE1_SCORES), FakeClient({"nope": 0.9}))
    assert preview.fallback and preview.stage2_skip_reason == "bad_payload"


async def test_autonomy_decidable_with_margin() -> None:
    preview = await _run(FakeClient(_STAGE1_SCORES), FakeClient({"debug": 0.9, "tdd": 0.5, "react": 0.4, "plan_then_execute": 0.1, "review_only": 0.1}))
    assert preview.auto_decidable is True


async def test_autonomy_blocked_when_top_tied_with_margin_required() -> None:
    judgment = FakeClient({"debug": 0.9, "tdd": 0.85, "react": 0.4, "plan_then_execute": 0.1, "review_only": 0.1})
    preview = await _run(FakeClient(_STAGE1_SCORES), judgment)
    assert preview.auto_decidable is False
    relaxed = await _run(FakeClient(_STAGE1_SCORES), judgment, autonomy_require_margin=False)
    assert relaxed.auto_decidable is True


async def test_autonomy_blocked_when_top_below_min_fit() -> None:
    judgment = FakeClient({"debug": 0.6, "tdd": 0.2, "react": 0.2, "plan_then_execute": 0.1, "review_only": 0.1})
    preview = await _run(FakeClient(_STAGE1_SCORES), judgment)
    assert preview.auto_decidable is False
    relaxed = await _run(FakeClient(_STAGE1_SCORES), judgment, autonomy_min_fit="Medium")
    assert relaxed.auto_decidable is True


async def test_react_injected_when_no_candidates_match_capabilities() -> None:
    react = PatternDoc(id="react", name="ReAct", kind="family", schema_version=1, version=1, status="active", description="d", required_capabilities=["exotic"], expected_cost_class="Med")
    registry = PatternRegistry([react])
    judgment = FakeClient({"react": 0.8})
    preview = await preview_strategies(task_instruction="x", acceptance_criteria="y", registry=registry, relevance=FakeClient(_STAGE1_SCORES), judgment=judgment, available_capabilities=set())
    assert [c["id"] for c in judgment.calls[0]["catalog"]] == ["react"]
    assert preview.recommended is not None and preview.recommended.family_id == "react"
    assert not preview.fallback


async def test_empty_registry_falls_back_with_no_recommendation() -> None:
    preview = await preview_strategies(task_instruction="x", acceptance_criteria="y", registry=PatternRegistry([]), relevance=FakeClient(_STAGE1_SCORES), judgment=FakeClient({"react": 0.8}), available_capabilities=_CAPS)
    assert preview.fallback and preview.recommended is None and preview.auto_decidable is False


async def test_top3_is_serialized_field_and_ranked_stays_full() -> None:
    preview = await _run(FakeClient(_STAGE1_SCORES), FakeClient({"debug": 0.9, "tdd": 0.6, "react": 0.5, "plan_then_execute": 0.2, "review_only": 0.1}))
    data = dataclasses.asdict(preview)
    assert "top3" in data and len(data["top3"]) <= 3
    assert [r["family_id"] for r in data["top3"]] == ["debug", "tdd", "react"]
    assert len(data["ranked"]) == 5
    fallback = dataclasses.asdict(await _run(NullDecisionClient(), NullDecisionClient()))
    assert [r["family_id"] for r in fallback["top3"]] == ["react"]


async def test_partial_stage2_scores_fall_back_to_react() -> None:
    preview = await _run(FakeClient(_STAGE1_SCORES), FakeClient({"debug": 0.95, "tdd": 0.1}))
    assert preview.fallback and preview.stage2_skipped
    assert preview.stage2_skip_reason == "bad_payload" and preview.skip_reason == "bad_payload"
    assert [r.family_id for r in preview.ranked] == ["react"]
    assert preview.ranked[0].why == ["selection_fallback"]
    assert preview.scores == {}
