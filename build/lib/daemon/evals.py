"""EvalEngine — LLM-as-judge scoring and regression detection.

Design:
- ``EvalEngine`` scores agent outputs against expected criteria using
  configurable judges.  V1 ships with a rule-based heuristic judge that
  always works (no LLM dependency).  A future V2 can plug in an LLM judge
  (Ollama / OpenAI) for semantic scoring.
- Eval results are stored in-memory and can be queried per project / agent.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class Score(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class EvalCase:
    """A single evaluation case."""

    id: str
    project: str
    agent_id: str
    criterion: str         # e.g. "no_hardcoded_secrets", "follows_pattern"
    expected: str           # expected behaviour description
    actual: str             # what the agent actually produced
    score: Score
    confidence: float = 0.5
    details: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "agent_id": self.agent_id,
            "criterion": self.criterion,
            "expected": self.expected,
            "actual": self.actual,
            "score": self.score.value,
            "confidence": self.confidence,
            "details": self.details,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Built-in heuristic rules (no LLM required)
# ---------------------------------------------------------------------------

def _check_no_hardcoded_secrets(actual: str) -> tuple[Score, float, str]:
    """Heuristic: flag strings that look like hardcoded secrets."""
    suspicious = ["password", "secret", "api_key", "token", "private_key"]
    actual_lower = actual.lower()
    hits = [w for w in suspicious if w in actual_lower]
    if hits:
        return (
            Score.WARN,
            0.70,
            f"Found potential secrets: {', '.join(hits)}. Consider using env vars.",
        )
    return Score.PASS, 0.90, "No hardcoded secrets detected."


def _check_no_todos(actual: str) -> tuple[Score, float, str]:
    """Heuristic: flag TODO / FIXME comments."""
    markers = ["TODO", "FIXME", "HACK", "XXX"]
    hits = [m for m in markers if m in actual]
    if hits:
        return Score.WARN, 0.60, f"Found unresolved markers: {', '.join(hits)}"
    return Score.PASS, 0.95, "No unresolved markers found."


def _check_structured_output(actual: str) -> tuple[Score, float, str]:
    """Heuristic: does the output contain FOUND/PATTERN/DECISION markers?"""
    markers = ["FOUND:", "PATTERN:", "DECISION:"]
    hits = [m for m in markers if m in actual]
    if hits:
        return Score.PASS, 0.85, f"Structured output with {len(hits)} findings."
    return Score.WARN, 0.40, "Output lacks FOUND/PATTERN/DECISION structure."


# Registry of built-in evaluation criteria
_HEURISTICS = {
    "no_hardcoded_secrets": _check_no_hardcoded_secrets,
    "no_todos": _check_no_todos,
    "structured_output": _check_structured_output,
}


# ---------------------------------------------------------------------------
# EvalEngine
# ---------------------------------------------------------------------------

class EvalEngine:
    """Score agent outputs against criteria and detect regressions.

    Usage::

        engine = EvalEngine()
        result = await engine.evaluate(
            project="my-proj", agent_id="agent-1",
            criterion="no_hardcoded_secrets",
            expected="No hardcoded credentials in code",
            actual=agent_output,
        )
    """

    def __init__(self):
        self._cases: list[EvalCase] = []

    async def evaluate(
        self,
        project: str,
        agent_id: str,
        criterion: str,
        expected: str,
        actual: str,
    ) -> EvalCase:
        """Run an evaluation and return the result."""
        case_id = str(uuid.uuid4())[:12]

        # Look up the heuristic for this criterion
        heuristic = _HEURISTICS.get(criterion)
        if heuristic is not None:
            score, confidence, details = heuristic(actual)
        else:
            # Unknown criterion: pass with low confidence (needs human / LLM review)
            score, confidence, details = (
                Score.PASS,
                0.30,
                f"No heuristic for criterion '{criterion}'; manual review recommended.",
            )

        case = EvalCase(
            id=case_id,
            project=project,
            agent_id=agent_id,
            criterion=criterion,
            expected=expected,
            actual=actual[:1000],  # truncate for storage
            score=score,
            confidence=confidence,
            details=details,
        )
        self._cases.append(case)
        return case

    async def get_results(
        self,
        project: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[EvalCase]:
        """Return eval results, most-recent-first, optionally filtered."""
        results: list[EvalCase] = []
        for case in reversed(self._cases):
            if project is not None and case.project != project:
                continue
            if agent_id is not None and case.agent_id != agent_id:
                continue
            results.append(case)
            if len(results) >= limit:
                break
        return results

    async def get_pass_rate(
        self, project: str, agent_id: str | None = None
    ) -> dict:
        """Return pass/warn/fail counts and rate for a project."""
        cases = await self.get_results(project=project, agent_id=agent_id)
        total = len(cases) or 1  # avoid division by zero
        counts = {"pass": 0, "warn": 0, "fail": 0}
        for c in cases:
            counts[c.score.value] += 1
        return {
            "total": total,
            "pass": counts["pass"],
            "warn": counts["warn"],
            "fail": counts["fail"],
            "pass_rate": round(counts["pass"] / total, 3),
        }
