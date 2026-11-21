"""Tests for the ReAct PatternRunner."""

from __future__ import annotations

import json
from pathlib import Path

from coding_agent.events import JsonlEventSink
from coding_agent.ports import LlmPort, LlmReply
from coding_agent.runners.base import PatternRunner
from coding_agent.runners.react import ReactRunner
from coding_agent.session import RunSession
from coding_agent.testing.fakes import FakeSandbox, FakeUsageMeter


class ScriptedLlm:
    def __init__(self, contents: list[str], *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.contents = contents
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    def chat(self, messages: list[dict], *, model: str) -> LlmReply:
        index = self.calls
        self.calls += 1
        if index >= len(self.contents):
            raise AssertionError(f"unexpected llm call {self.calls}")
        return LlmReply(
            content=self.contents[index],
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class _CancelAfterFirst:
    def __init__(self, session_box: dict) -> None:
        self.session_box = session_box
        self.calls = 0

    def chat(self, messages: list[dict], *, model: str) -> LlmReply:
        self.calls += 1
        self.session_box["session"].request_cancel()
        return LlmReply(content=_action("still working", None, done=False))


class _Context:
    def pack(self) -> str:
        return ""


def _action(thought: str, tool: str | None, args: dict | None = None, done: bool = False) -> str:
    return json.dumps({"thought": thought, "tool": tool, "args": args or {}, "done": done})


def _session(tmp_path: Path, llm: LlmPort, **manifest: object) -> RunSession:
    root = tmp_path / "sandbox"
    root.mkdir(exist_ok=True)
    return RunSession(
        manifest,
        FakeSandbox(root),
        JsonlEventSink(tmp_path / "events.jsonl"),
        llm,
        FakeUsageMeter(),
        _Context(),
    )


def _events(tmp_path: Path) -> list[dict]:
    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def test_react_think_edit_done_changes_file_and_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "hello.txt").write_text("hello\n", encoding="utf-8")
    llm = ScriptedLlm(
        [
            _action("read the task", None),
            _action(
                "replace greeting",
                "edit",
                {"path": "hello.txt", "search": "hello\n", "replace": "world\n"},
            ),
            _action("the file is updated", None, done=True),
        ]
    )
    session = _session(tmp_path, llm, prompt="change hello to world", model="fake")
    runner = ReactRunner()
    assert isinstance(runner, PatternRunner)

    outcome = runner.run(session)

    assert outcome.status == "succeeded"
    assert outcome.stop_reason == "done"
    assert (root / "hello.txt").read_text(encoding="utf-8") == "world\n"
    assert llm.calls == 3
    assert _events(tmp_path)[-1] == {"type": "run.succeeded", "stop_reason": "done"}


def test_budget_mid_loop_emits_failed_and_stops_llm(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "hello.txt").write_text("hello\n", encoding="utf-8")
    llm = ScriptedLlm(
        [
            _action(
                "edit once",
                "edit",
                {"path": "hello.txt", "search": "hello\n", "replace": "world\n"},
            ),
            _action("should not run", None, done=True),
        ]
    )
    session = _session(tmp_path, llm, step_limit=1)

    outcome = ReactRunner().run(session)

    assert outcome.status == "failed"
    assert outcome.stop_reason == "budget_step"
    assert llm.calls == 1
    assert (root / "hello.txt").read_text(encoding="utf-8") == "world\n"
    events = _events(tmp_path)
    assert events[-1] == {"type": "run.failed", "stop_reason": "budget_step"}
    assert not any(event["type"] == "run.succeeded" for event in events)


def test_token_budget_after_reply_stops_next_llm_call(tmp_path: Path) -> None:
    llm = ScriptedLlm(
        [
            _action("think", None),
            _action("should not run", None, done=True),
        ],
        input_tokens=10,
    )
    session = _session(tmp_path, llm, token_limit=10)

    outcome = ReactRunner().run(session)

    assert outcome.status == "failed"
    assert outcome.stop_reason == "budget_token"
    assert llm.calls == 1
    assert _events(tmp_path)[-1] == {"type": "run.failed", "stop_reason": "budget_token"}


def test_cancel_before_start_does_not_call_llm(tmp_path: Path) -> None:
    llm = ScriptedLlm([_action("should not run", None, done=True)])
    session = _session(tmp_path, llm)
    session.request_cancel()

    outcome = ReactRunner().run(session)

    assert outcome.status == "cancelled"
    assert outcome.stop_reason == "cancelled"
    assert llm.calls == 0
    assert _events(tmp_path)[-1] == {"type": "run.cancelled", "stop_reason": "cancelled"}


def test_cancel_between_steps_emits_cancelled_without_further_llm(tmp_path: Path) -> None:
    box: dict = {}
    llm = _CancelAfterFirst(box)
    session = _session(tmp_path, llm)
    box["session"] = session

    outcome = ReactRunner().run(session)

    assert outcome.status == "cancelled"
    assert outcome.stop_reason == "cancelled"
    assert llm.calls == 1
    assert _events(tmp_path)[-1] == {"type": "run.cancelled", "stop_reason": "cancelled"}


def test_invalid_action_json_fails_without_another_llm_call(tmp_path: Path) -> None:
    llm = ScriptedLlm(["not json", _action("should not run", None, done=True)])
    session = _session(tmp_path, llm)

    outcome = ReactRunner().run(session)

    assert outcome.status == "failed"
    assert outcome.stop_reason == "invalid_action"
    assert llm.calls == 1
    assert _events(tmp_path)[-1] == {"type": "run.failed", "stop_reason": "invalid_action"}
