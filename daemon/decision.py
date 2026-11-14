"""Pluggable decision layer — normalized DecisionResult and client protocol."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

SkipReason = Literal["none", "error", "timeout", "bad_payload", "unsupported"]
ProviderId = Literal["typesafe", "ollama", "gliclass", "none"]


@dataclass
class DecisionUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class DecisionResult:
    scores: dict[str, float] = field(default_factory=dict)
    usage: DecisionUsage = field(default_factory=DecisionUsage)
    provider: ProviderId = "none"
    model: str = ""
    skipped: bool = False
    skip_reason: SkipReason | None = None
    latency_ms: float = 0.0


def _null_result() -> DecisionResult:
    t0 = time.perf_counter()
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return DecisionResult(
        scores={},
        usage=DecisionUsage(input_tokens=None, output_tokens=None),
        provider="none",
        model="",
        skipped=True,
        skip_reason="none",
        latency_ms=latency_ms,
    )


@runtime_checkable
class DecisionClient(Protocol):
    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult: ...

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult: ...


class NullDecisionClient:
    """Judgment/filter no-op: always skipped with reason ``none`` (orchestrator escalates)."""

    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult:
        return _null_result()

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult:
        return _null_result()