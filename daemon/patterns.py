"""Self-evolving pattern repository — learns from agent findings over time.

Design:
- Agents report FOUND / PATTERN / DECISION observations.
- ``PatternRepository`` normalises, deduplicates, and tracks each pattern
  across projects and agents.
- Confidence increases with observations; cross-project sightings fast-track
  a pattern from CANDIDATE → VERIFIED → ESTABLISHED.
- All state is in-memory (V1).  Future V2 can persist to SQLite for
  crash recovery and cold-start from existing findings.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class PatternStatus(str, Enum):
    CANDIDATE = "candidate"       # seen 1-2 times
    VERIFIED = "verified"          # seen across 3+ projects or 5+ observations
    ESTABLISHED = "established"    # seen 10+ times, high confidence
    DEPRECATED = "deprecated"      # manually marked obsolete


@dataclass
class Pattern:
    """A self-evolving knowledge pattern."""

    id: str
    pattern_text: str                # normalised text
    status: PatternStatus = PatternStatus.CANDIDATE
    confidence: float = 0.3
    observation_count: int = 1
    projects: set[str] = field(default_factory=set)
    agents: set[str] = field(default_factory=set)
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    deprecation_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pattern_text": self.pattern_text,
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "observation_count": self.observation_count,
            "projects": sorted(self.projects),
            "agents": sorted(self.agents),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "deprecation_reason": self.deprecation_reason,
        }


class PatternRepository:
    """Tracks and evolves patterns from agent observations.

    Patterns are normalised (whitespace-collapsed, lowercased) before
    deduplication.  Observation boosts confidence and can promote the
    pattern through its lifecycle.
    """

    # Thresholds for status promotion
    VERIFIED_MIN_PROJECTS = 3
    VERIFIED_MIN_OBSERVATIONS = 5
    ESTABLISHED_MIN_OBSERVATIONS = 10

    def __init__(self):
        self._patterns: dict[str, Pattern] = {}  # keyed by normalised text
        self._key_to_id: dict[str, str] = {}      # normalised_text → pattern.id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def observe(
        self,
        pattern_text: str,
        project: str,
        agent_id: str,
        kind: str = "PATTERN",
    ) -> Pattern:
        """Record an observation of a pattern.  Returns the (possibly new) pattern."""
        key = self._normalise(pattern_text)

        if key in self._key_to_id:
            pattern = await self.get_pattern(self._key_to_id[key])
            if pattern is None:
                # Shouldn't happen — repair
                return await self._create_pattern(key, project, agent_id, kind)
        else:
            pattern = await self._create_pattern(key, project, agent_id, kind)
            return pattern

        # Update existing
        pattern.observation_count += 1
        pattern.projects.add(project)
        pattern.agents.add(agent_id)
        pattern.last_seen = datetime.now(timezone.utc).isoformat()

        # Recompute confidence
        pattern.confidence = self._compute_confidence(pattern)

        # Recompute status
        pattern.status = self._compute_status(pattern)

        return pattern

    async def get_pattern(self, pattern_id: str) -> Pattern | None:
        return self._patterns.get(pattern_id)

    async def list_patterns(
        self,
        project: str | None = None,
        status: PatternStatus | None = None,
        limit: int = 50,
    ) -> list[Pattern]:
        """Return patterns, optionally filtered by project or status."""
        results: list[Pattern] = []
        for p in self._patterns.values():
            if status is not None and p.status != status:
                continue
            if project is not None and project not in p.projects:
                continue
            results.append(p)
        results.sort(key=lambda p: p.confidence, reverse=True)
        return results[:limit]

    async def top_patterns(self, limit: int = 10) -> list[Pattern]:
        """Return the highest-confidence patterns."""
        return await self.list_patterns(limit=limit)

    async def cross_project_patterns(self) -> list[Pattern]:
        """Return patterns seen in 2+ projects."""
        return sorted(
            [p for p in self._patterns.values() if len(p.projects) >= 2],
            key=lambda p: p.confidence,
            reverse=True,
        )

    async def deprecate(self, pattern_id: str, reason: str = "") -> Pattern | None:
        """Mark a pattern as deprecated."""
        pattern = self._patterns.get(pattern_id)
        if pattern is None:
            return None
        pattern.status = PatternStatus.DEPRECATED
        pattern.deprecation_reason = reason
        pattern.last_seen = datetime.now(timezone.utc).isoformat()
        return pattern

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _normalise(self, text: str) -> str:
        """Normalise pattern text for deduplication."""
        # Collapse whitespace, lowercase, strip punctuation edge
        text = text.strip().lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[.,;:!?]+$", "", text)
        return text

    async def _create_pattern(
        self, key: str, project: str, agent_id: str, kind: str,
    ) -> Pattern:
        """Create a brand-new pattern from a first observation."""
        pattern_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()

        pattern = Pattern(
            id=pattern_id,
            pattern_text=key,
            first_seen=now,
            last_seen=now,
            projects={project},
            agents={agent_id},
        )
        self._patterns[pattern_id] = pattern
        self._key_to_id[key] = pattern_id
        return pattern

    def _compute_confidence(self, p: Pattern) -> float:
        """Compute confidence based on observation count and project spread.

        Starts at 0.3 for the first observation and grows by 0.1 per
        additional observation AND 0.1 per additional project.
        """
        obs = p.observation_count
        proj = len(p.projects)
        raw = 0.3 + (obs - 1) * 0.1 + (proj - 1) * 0.1
        return round(min(raw, 0.99), 3)

    def _compute_status(self, p: Pattern) -> PatternStatus:
        """Determine pattern lifecycle status from its stats."""
        if p.observation_count >= self.ESTABLISHED_MIN_OBSERVATIONS:
            return PatternStatus.ESTABLISHED
        if (
            len(p.projects) >= self.VERIFIED_MIN_PROJECTS
            or p.observation_count >= self.VERIFIED_MIN_OBSERVATIONS
        ):
            return PatternStatus.VERIFIED
        return PatternStatus.CANDIDATE
