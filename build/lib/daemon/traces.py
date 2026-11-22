"""Agent execution tracing — captures spans for every agent turn and tool call.

Design:
- ``TraceSpan`` is a lightweight record of a single unit of work (agent turn,
  tool call, LLM inference).  Spans form a tree via ``parent_id``.
- ``TraceCapture`` is an in-memory ring buffer capped at 10 000 spans.  Older
  spans are silently evicted.  A future V2 can persist traces to SQLite
  for longer retention.
- All operations are async (non-blocking by design — callers can fire and
  forget without a performance penalty).
"""

from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Default ring-buffer size
_DEFAULT_MAX_SPANS = 10_000


class SpanKind(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    LLM = "llm"
    RECALL = "recall"
    RETAIN = "retain"
    EXTRACT = "extract"


@dataclass
class TraceSpan:
    """A single traced unit of work."""

    id: str
    name: str
    kind: SpanKind
    project: str
    agent_id: str
    parent_id: str | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    latency_ms: float | None = None
    input_data: dict | None = None
    output_data: dict | None = None
    metadata: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "project": self.project,
            "agent_id": self.agent_id,
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "latency_ms": self.latency_ms,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "metadata": self.metadata,
            "error": self.error,
        }


class TraceCapture:
    """In-memory ring-buffer for agent execution traces.

    Usage::

        capture = TraceCapture()
        span = await capture.start_span("my-agent", SpanKind.AGENT, "proj", "a1")
        # ... do work ...
        await capture.finish_span(span.id, output_data={"result": "ok"})
    """

    def __init__(self, max_spans: int = _DEFAULT_MAX_SPANS):
        self._max_spans = max(1, max_spans)
        self._spans: list[TraceSpan] = []
        self._by_id: dict[str, TraceSpan] = {}

    async def start_span(
        self,
        name: str,
        kind: SpanKind,
        project: str,
        agent_id: str,
        parent_id: str | None = None,
        input_data: dict | None = None,
    ) -> TraceSpan:
        """Create and record a new span.  Returns the span so the caller can
        reference it later when calling ``finish_span``."""
        span_id = str(uuid.uuid4())[:12]
        span = TraceSpan(
            id=span_id,
            name=name,
            kind=kind,
            project=project,
            agent_id=agent_id,
            parent_id=parent_id,
            input_data=input_data,
        )
        self._spans.append(span)
        self._by_id[span_id] = span
        self._evict_oldest()
        return span

    async def finish_span(
        self,
        span_id: str,
        output_data: dict | None = None,
        metadata: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Finalise a previously started span."""
        span = self._by_id.get(span_id)
        if span is None:
            logger.debug("finish_span: unknown span id %s", span_id)
            return
        if span.end_time is not None:
            return  # already finished — idempotent no-op
        span.end_time = time.monotonic()
        span.latency_ms = (span.end_time - span.start_time) * 1000
        if output_data is not None:
            span.output_data = output_data
        if metadata is not None:
            span.metadata.update(metadata)
        span.error = error

    async def get_spans(
        self,
        project: str | None = None,
        agent_id: str | None = None,
        kind: SpanKind | None = None,
        limit: int = 100,
    ) -> list[TraceSpan]:
        """Return spans, most-recent-first, optionally filtered."""
        results: list[TraceSpan] = []
        for span in reversed(self._spans):
            if project is not None and span.project != project:
                continue
            if agent_id is not None and span.agent_id != agent_id:
                continue
            if kind is not None and span.kind != kind:
                continue
            results.append(span)
            if len(results) >= limit:
                break
        return results

    def _evict_oldest(self):
        """Drop the oldest spans when the ring buffer is full."""
        while len(self._spans) > self._max_spans:
            removed = self._spans.pop(0)
            self._by_id.pop(removed.id, None)
