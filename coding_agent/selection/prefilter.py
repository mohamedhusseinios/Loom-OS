"""Stage-1 family prefilter (pure)."""

from __future__ import annotations

from coding_agent.patterns.schema import PatternDoc
from coding_agent.selection.types import StrategyCandidate, TaskProfile


def prefilter_families(docs: list[PatternDoc], *, profile: TaskProfile, available_capabilities: set[str], anti_hit_ids: set[str] | None = None, limit: int = 5) -> list[StrategyCandidate]:
    del profile  # reserved for later Stage-1 signal; shape fixed for callers
    blocked = anti_hit_ids or set()
    candidates: list[StrategyCandidate] = []
    for doc in docs:
        if doc.status != "active":
            continue
        if blocked and doc.id in blocked:
            continue
        required = set(doc.required_capabilities)
        if required and not required.issubset(available_capabilities):
            continue
        candidates.append(StrategyCandidate(family_id=doc.id, modifier_ids=[], doc=doc))
        if len(candidates) >= limit:
            break
    return candidates