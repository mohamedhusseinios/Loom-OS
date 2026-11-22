"""Tests for daemon coding_agent adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.events import JsonlEventSink
from coding_agent.session import BudgetExceeded, RunSession
from coding_agent.testing.fakes import FakeSandbox
from daemon.coding_adapters import SimpleUsageMeter, StubContextSource


class _Llm:
    def chat(self, messages: list[dict], *, model: str) -> None:
        raise AssertionError("llm should not be called")


def test_simple_usage_meter_estimates_cost_from_tokens() -> None:
    meter = SimpleUsageMeter()
    meter.add_tokens(1_000_000, 0)
    assert meter.cost_usd() > 0.0
    meter.add_tokens(0, 1_000_000)
    total = meter.cost_usd()
    assert total >= 0.14 + 0.28 - 1e-9  # one MTok in + one MTok out at defaults


def test_simple_usage_meter_trips_session_cost_limit(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    session = RunSession(
        {"cost_limit_usd": 0.01, "token_limit": 10_000_000},
        FakeSandbox(root),
        JsonlEventSink(tmp_path / "events.jsonl"),
        _Llm(),
        SimpleUsageMeter(),
        StubContextSource(),
    )
    session.meter.add_tokens(100_000, 100_000)
    with pytest.raises(BudgetExceeded) as exc_info:
        session.check_can_continue()
    assert exc_info.value.reason == "cost"