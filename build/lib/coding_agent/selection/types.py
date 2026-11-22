"""Selection types (pure; no daemon imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from coding_agent.patterns.schema import PatternDoc

FitLevel = Literal["High", "Medium", "Low"]

_FIT_ORDER: dict[FitLevel, int] = {"High": 2, "Medium": 1, "Low": 0}


def fit_rank(level: FitLevel) -> int:
    return _FIT_ORDER[level]


@dataclass(frozen=True)
class TaskProfile:
    type: str
    size: str
    risk: str
    has_tests: bool
    repo_familiarity: str


@dataclass(frozen=True)
class StrategyCandidate:
    family_id: str
    modifier_ids: list[str]
    doc: PatternDoc


@dataclass(frozen=True)
class RankedStrategy:
    family_id: str
    modifier_ids: list[str]
    fit: FitLevel
    why: list[str]
    expected_cost_class: str | None
    name: str