"""Shared DecisionClient contract tests — Null client first; Jev/GLiClass in later tasks."""
import pytest

from daemon.decision import DecisionResult, NullDecisionClient


@pytest.fixture
def null_client() -> NullDecisionClient:
    return NullDecisionClient()


def test_null_judge_returns_skipped_none_provider(null_client: NullDecisionClient):
    result = null_client.judge(pack="context", task=None, catalog=[], candidates=[])
    assert isinstance(result, DecisionResult)
    assert result.skipped is True
    assert result.skip_reason == "none"
    assert result.provider == "none"
    assert result.model == ""
    assert result.scores == {}
    assert result.usage.input_tokens is None
    assert result.latency_ms >= 0


def test_null_filter_relevance_returns_skipped_none_provider(null_client: NullDecisionClient):
    result = null_client.filter_relevance(pack="context", task=None, catalog=[], hits=[])
    assert result.skipped is True
    assert result.skip_reason == "none"
    assert result.provider == "none"
    assert result.usage.input_tokens is None
    assert result.latency_ms >= 0