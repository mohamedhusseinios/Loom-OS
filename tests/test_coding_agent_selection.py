"""Tests for pure pattern selection helpers (no daemon)."""

from __future__ import annotations

import pytest

from coding_agent.patterns import PatternDoc
from coding_agent.selection import (
    FitLevel,
    RankedStrategy,
    StrategyCandidate,
    TaskProfile,
    autonomy_decidable,
    fit_level_from_score,
    prefilter_families,
    rank_strategies,
)

_PROFILE = TaskProfile(
    type="feature",
    size="small",
    risk="low",
    has_tests=True,
    repo_familiarity="high",
)


def _family(id: str, *, status: str = "active", required_capabilities: list[str] | None = None, expected_cost_class: str | None = "Med", name: str | None = None) -> PatternDoc:
    return PatternDoc(
        id=id,
        name=name or id.replace("_", " ").title(),
        kind="family",
        schema_version=1,
        version=1,
        status=status,  # type: ignore[arg-type]
        description=f"{id} pattern",
        required_capabilities=required_capabilities or [],
        expected_cost_class=expected_cost_class,  # type: ignore[arg-type]
    )


def _candidate(doc: PatternDoc) -> StrategyCandidate:
    return StrategyCandidate(family_id=doc.id, modifier_ids=[], doc=doc)


def _ranked(family_id: str, fit: FitLevel, *, why: list[str] | None = None) -> RankedStrategy:
    return RankedStrategy(
        family_id=family_id,
        modifier_ids=[],
        fit=fit,
        why=why or [],
        expected_cost_class="Med",
        name=family_id,
    )


def test_prefilter_excludes_planned_status() -> None:
    docs = [_family("react"), _family("tdd", status="planned")]
    out = prefilter_families(
        docs,
        profile=_PROFILE,
        available_capabilities={"read", "edit"},
    )
    assert [c.family_id for c in out] == ["react"]
    assert out[0].modifier_ids == []


def test_prefilter_excludes_unmet_required_capabilities() -> None:
    docs = [
        _family("react"),
        _family("review_only", required_capabilities=["git", "read"]),
    ]
    out = prefilter_families(
        docs,
        profile=_PROFILE,
        available_capabilities={"read"},
    )
    assert [c.family_id for c in out] == ["react"]


def test_prefilter_excludes_anti_hit_ids() -> None:
    docs = [_family("react"), _family("tdd"), _family("debug")]
    out = prefilter_families(
        docs,
        profile=_PROFILE,
        available_capabilities=set(),
        anti_hit_ids={"tdd"},
    )
    assert [c.family_id for c in out] == ["react", "debug"]


def test_prefilter_respects_limit_preserving_order() -> None:
    docs = [_family("a"), _family("b"), _family("c"), _family("d")]
    out = prefilter_families(
        docs,
        profile=_PROFILE,
        available_capabilities=set(),
        limit=2,
    )
    assert [c.family_id for c in out] == ["a", "b"]


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.75, "High"),
        (1.0, "High"),
        (0.74, "Medium"),
        (0.4, "Medium"),
        (0.39, "Low"),
        (0.0, "Low"),
    ],
)
def test_fit_level_from_score_bands(score: float, expected: FitLevel) -> None:
    assert fit_level_from_score(score) == expected


def test_rank_strategies_orders_by_fit_then_score_then_family_id() -> None:
    candidates = [
        _candidate(_family("z_low")),
        _candidate(_family("a_high")),
        _candidate(_family("m_med")),
    ]
    scores = {"z_low": 0.9, "a_high": 0.8, "m_med": 0.5}
    why_by_id = {"z_low": ["z"], "a_high": ["a"], "m_med": ["m"]}
    ranked = rank_strategies(candidates, scores, why_by_id)
    assert [r.family_id for r in ranked] == ["z_low", "a_high", "m_med"]
    assert [r.fit for r in ranked] == ["High", "High", "Medium"]
    assert ranked[0].why == ["z"]
    assert ranked[1].name == "A High"


def test_rank_strategies_tiebreaks_equal_fit_by_score_then_family_id() -> None:
    candidates = [
        _candidate(_family("bravo")),
        _candidate(_family("alpha")),
        _candidate(_family("charlie")),
    ]
    scores = {"alpha": 0.9, "bravo": 0.85, "charlie": 0.9}
    ranked = rank_strategies(candidates, scores, {})
    assert [r.family_id for r in ranked] == ["alpha", "charlie", "bravo"]


def test_autonomy_decidable_empty_is_false() -> None:
    assert autonomy_decidable([]) is False


def test_autonomy_decidable_with_margin_requires_strictly_higher_top_fit() -> None:
    ranked = [_ranked("a", "High"), _ranked("b", "High")]
    assert autonomy_decidable(ranked, require_margin=True) is False

    ranked_margin = [_ranked("a", "High"), _ranked("b", "Medium")]
    assert autonomy_decidable(ranked_margin, require_margin=True) is True

    single = [_ranked("only", "High")]
    assert autonomy_decidable(single, require_margin=True) is True


def test_autonomy_decidable_without_margin_ignores_second_place() -> None:
    ranked = [_ranked("a", "High"), _ranked("b", "High")]
    assert autonomy_decidable(ranked, require_margin=False) is True


def test_autonomy_decidable_respects_min_fit() -> None:
    ranked = [_ranked("a", "Medium"), _ranked("b", "Low")]
    assert autonomy_decidable(ranked, min_fit="High", require_margin=True) is False
    assert autonomy_decidable(ranked, min_fit="Medium", require_margin=False) is True