"""Tests for the TraceCapture observability system."""
import pytest
from daemon.traces import TraceCapture, TraceSpan, SpanKind


@pytest.fixture
def capture():
    return TraceCapture()


@pytest.mark.asyncio
async def test_start_and_finish_span(capture):
    """A span can be started, yielded to, and finished."""
    span = await capture.start_span(
        name="agent-turn",
        kind=SpanKind.AGENT,
        project="test-proj",
        agent_id="agent-1",
    )
    assert span.id
    assert span.name == "agent-turn"
    assert span.kind == SpanKind.AGENT
    assert span.start_time is not None
    assert span.end_time is None  # not finished yet

    await capture.finish_span(span.id, metadata={"tokens": 1500})
    assert span.end_time is not None
    assert span.metadata["tokens"] == 1500


@pytest.mark.asyncio
async def test_tool_span_child_of_agent(capture):
    """Tool spans can be nested under an agent span."""
    agent = await capture.start_span("run", SpanKind.AGENT, "proj", "a1")

    tool = await capture.start_span(
        name="read_file",
        kind=SpanKind.TOOL,
        project="proj",
        agent_id="a1",
        parent_id=agent.id,
        input_data={"path": "auth.py"},
    )
    assert tool.parent_id == agent.id
    assert tool.input_data["path"] == "auth.py"

    await capture.finish_span(tool.id, output_data={"lines": 100})
    await capture.finish_span(agent.id)

    assert tool.end_time is not None
    assert tool.output_data["lines"] == 100


@pytest.mark.asyncio
async def test_get_spans_for_project(capture):
    """Spans are filterable by project."""
    await capture.start_span("a1", SpanKind.AGENT, "proj-a", "x")
    await capture.start_span("a2", SpanKind.AGENT, "proj-b", "y")

    spans_a = await capture.get_spans(project="proj-a")
    assert len(spans_a) == 1
    assert spans_a[0].project == "proj-a"


@pytest.mark.asyncio
async def test_get_spans_for_agent(capture):
    """Spans are filterable by agent."""
    await capture.start_span("run", SpanKind.AGENT, "proj", "agent-x")
    await capture.start_span("run", SpanKind.AGENT, "proj", "agent-y")

    spans = await capture.get_spans(agent_id="agent-x")
    assert len(spans) == 1
    assert spans[0].agent_id == "agent-x"


@pytest.mark.asyncio
async def test_get_spans_most_recent_first(capture):
    """Spans are returned in most-recent-first order."""
    s1 = await capture.start_span("first", SpanKind.AGENT, "proj", "a")
    s2 = await capture.start_span("second", SpanKind.AGENT, "proj", "a")
    await capture.finish_span(s1.id)
    await capture.finish_span(s2.id)

    spans = await capture.get_spans(project="proj")
    assert len(spans) == 2
    assert spans[0].id == s2.id
    assert spans[1].id == s1.id


@pytest.mark.asyncio
async def test_finish_nonexistent_span_no_error(capture):
    """Finishing a span that doesn't exist is a silent no-op."""
    await capture.finish_span("nonexistent")


@pytest.mark.asyncio
async def test_span_latency_computed(capture):
    """Span latency is computed when the span finishes."""
    span = await capture.start_span("test", SpanKind.AGENT, "proj", "a")
    await capture.finish_span(span.id)
    assert span.latency_ms is not None
    assert isinstance(span.latency_ms, float)
    assert span.latency_ms >= 0


@pytest.mark.asyncio
async def test_trace_capture_limit(capture):
    """TraceCapture caps the number of stored spans (ring buffer)."""
    # Override the limit to a small number for this test
    capture._max_spans = 5

    for i in range(10):
        s = await capture.start_span(f"s{i}", SpanKind.AGENT, "p", "a")
        await capture.finish_span(s.id)

    assert len(capture._spans) == 5
    # The oldest spans should have been evicted
    ids = [s.name for s in capture._spans]
    assert "s0" not in ids
    assert "s9" in ids


@pytest.mark.asyncio
async def test_finish_span_is_idempotent():
    cap = TraceCapture()
    span = await cap.start_span("t", SpanKind.TOOL, "p", "a1")
    await cap.finish_span(span.id, output_data={"n": 1})
    first_latency = span.latency_ms
    first_output = span.output_data
    # second finish must be a no-op (don't overwrite latency/output)
    await cap.finish_span(span.id, output_data={"n": 2})
    assert span.latency_ms == first_latency
    assert span.output_data == first_output


@pytest.mark.asyncio
async def test_eviction_clamps_and_keeps_newest():
    cap = TraceCapture(max_spans=0)          # must clamp to >=1, not self-evict
    s = await cap.start_span("t", SpanKind.TOOL, "p", "a1")
    assert (await cap.get_spans(project="p"))[0].id == s.id   # retained
    cap2 = TraceCapture(max_spans=2)
    ids = [(await cap2.start_span(f"s{i}", SpanKind.TOOL, "p", "a1")).id for i in range(3)]
    kept = {sp.id for sp in await cap2.get_spans(project="p")}
    assert kept == set(ids[1:])              # only the newest 2, oldest evicted
    assert ids[0] not in cap2._by_id         # _by_id stays in sync (no orphan)
