"""Fit bands, ranking, and autonomy decidable check (pure)."""

from __future__ import annotations

from coding_agent.selection.types import FitLevel, RankedStrategy, StrategyCandidate, fit_rank


def fit_level_from_score(score: float) -> FitLevel:
    if score >= 0.75:
        return "High"
    if score >= 0.4:
        return "Medium"
    return "Low"


def rank_strategies(
    candidates: list[StrategyCandidate],
    scores: dict[str, float],
    why_by_id: dict[str, list[str]],
) -> list[RankedStrategy]:
    ranked = [
        RankedStrategy(
            family_id=c.family_id,
            modifier_ids=list(c.modifier_ids),
            fit=fit_level_from_score(scores[c.family_id]),
            why=list(why_by_id.get(c.family_id, [])),
            expected_cost_class=c.doc.expected_cost_class,
            name=c.doc.name,
        )
        for c in candidates
    ]
    ranked.sort(
        key=lambda r: (-fit_rank(r.fit), -scores[r.family_id], r.family_id),
    )
    return ranked


def autonomy_decidable(
    ranked: list[RankedStrategy],
    *,
    min_fit: FitLevel = "High",
    require_margin: bool = True,
) -> bool:
    if not ranked:
        return False
    top = ranked[0]
    if fit_rank(top.fit) < fit_rank(min_fit):
        return False
    if not require_margin:
        return True
    if len(ranked) == 1:
        return True
    return fit_rank(top.fit) > fit_rank(ranked[1].fit)