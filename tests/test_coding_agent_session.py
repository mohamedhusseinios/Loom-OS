"""Tests for RunSession budgets and cancel."""

from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.events import JsonlEventSink
from coding_agent.session import BudgetExceeded, RunCancelled, RunSession
from coding_agent.testing.fakes import FakeSandbox, FakeUsageMeter


class _Llm:
    def chat(self, messages: list[dict], *, model: str) -> None:
        raise AssertionError("llm should not be called")


class _Context:
    def pack(self) -> str:
        return ""


def _session(tmp_path: Path, **manifest: object) -> RunSession:
    root = tmp_path / "sandbox"
    root.mkdir(exist_ok=True)
    return RunSession(
        manifest,
        FakeSandbox(root),
        JsonlEventSink(tmp_path / "events.jsonl"),
        _Llm(),
        FakeUsageMeter(),
        _Context(),
    )


def test_default_budgets(tmp_path: Path) -> None:
    session = _session(tmp_path)
    assert session.step_limit == 40
    assert session.token_limit == 100_000
    assert session.cost_limit_usd == 1.0
    session.check_can_continue()


def test_step_budget_stops(tmp_path: Path) -> None:
    session = _session(tmp_path, step_limit=2)
    session.record_step()
    session.check_can_continue()
    session.record_step()
    with pytest.raises(BudgetExceeded) as exc_info:
        session.check_can_continue()
    assert exc_info.value.reason == "step"


def test_token_budget_stops(tmp_path: Path) -> None:
    session = _session(tmp_path, token_limit=100)
    session.meter.add_tokens(60, 39)
    session.check_can_continue()
    session.meter.add_tokens(0, 1)
    with pytest.raises(BudgetExceeded) as exc_info:
        session.check_can_continue()
    assert exc_info.value.reason == "token"


def test_cost_budget_stops(tmp_path: Path) -> None:
    session = _session(tmp_path, cost_limit_usd=1.0)
    session.meter.set_cost_usd(0.99)
    session.check_can_continue()
    session.meter.set_cost_usd(1.0)
    with pytest.raises(BudgetExceeded) as exc_info:
        session.check_can_continue()
    assert exc_info.value.reason == "cost"


def test_cancel_flag_file_stops(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    session = _session(tmp_path, run_dir=str(run_dir))
    assert session.poll_cancel_file() is False
    session.check_can_continue()
    (run_dir / "cancel").write_text("", encoding="utf-8")
    assert session.poll_cancel_file() is True
    with pytest.raises(RunCancelled):
        session.check_can_continue()


def test_cancel_path_overrides_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    flag = tmp_path / "custom-cancel"
    session = _session(tmp_path, run_dir=str(run_dir), cancel_path=str(flag))
    (run_dir / "cancel").write_text("x", encoding="utf-8")
    assert session.poll_cancel_file() is False
    flag.write_text("x", encoding="utf-8")
    assert session.poll_cancel_file() is True
    with pytest.raises(RunCancelled):
        session.check_can_continue()


def test_request_cancel_stops(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.check_can_continue()
    session.request_cancel()
    with pytest.raises(RunCancelled):
        session.check_can_continue()


def test_dispatch_tool_unknown_is_not_implemented(tmp_path: Path) -> None:
    session = _session(tmp_path)
    assert session.dispatch_tool("not_a_tool", {}) == {
        "ok": False,
        "reason": "not_implemented",
    }


def test_poll_cancel_file_false_without_path(tmp_path: Path) -> None:
    session = _session(tmp_path)
    assert session.poll_cancel_file() is False
