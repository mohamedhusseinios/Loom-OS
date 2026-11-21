"""PatternRunner protocol and turn result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from coding_agent.session import RunSession

RunStatus = Literal["succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class TurnResult:
    thought: str
    tool: str | None
    args: dict[str, Any]
    done: bool


@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    stop_reason: str


@runtime_checkable
class PatternRunner(Protocol):
    def run(self, session: RunSession) -> RunOutcome: ...
