"""Tests for the ReAct PatternRunner."""

from __future__ import annotations

import json
from pathlib import Path

from coding_agent.events import JsonlEventSink
from coding_agent.ports import LlmPort, LlmReply
from coding_agent.runners.base import PatternRunner
from coding_agent.runners.react import TOOL_NAMES, ReactRunner, _SYSTEM
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


def test_fenced_json_action_parses_and_succeeds(tmp_path: Path) -> None:
    action = _action("finished", None, done=True)
    fenced = f"Here is the action:\n```json\n{action}\n```\n"
    llm = ScriptedLlm([fenced])
    session = _session(tmp_path, llm)

    outcome = ReactRunner().run(session)

    assert outcome.status == "succeeded"
    assert outcome.stop_reason == "done"
    assert llm.calls == 1


def test_prose_wrapped_json_object_parses(tmp_path: Path) -> None:
    payload = _action("wrap", None, done=True)
    wrapped = f"Sure! {payload} Thanks."
    llm = ScriptedLlm([wrapped])
    session = _session(tmp_path, llm)

    outcome = ReactRunner().run(session)

    assert outcome.status == "succeeded"
    assert outcome.stop_reason == "done"


def test_invalid_action_json_fails_without_another_llm_call(tmp_path: Path) -> None:
    llm = ScriptedLlm(["not json", _action("should not run", None, done=True)])
    session = _session(tmp_path, llm)

    outcome = ReactRunner().run(session)

    assert outcome.status == "failed"
    assert outcome.stop_reason == "invalid_action"
    assert llm.calls == 1
    assert _events(tmp_path)[-1] == {"type": "run.failed", "stop_reason": "invalid_action"}


def test_system_prompt_names_dispatch_tools() -> None:
    assert TOOL_NAMES == ("read_file", "edit", "search", "shell", "git", "run_tests", "run_lint")
    for name in TOOL_NAMES:
        assert name in _SYSTEM
    assert "git_status" not in _SYSTEM
    assert "git_diff" not in _SYSTEM
    assert '"tool": string or null' in _SYSTEM


def test_llm_exception_emits_run_failed(tmp_path: Path) -> None:
    class _Boom:
        def chat(self, messages: list[dict], *, model: str) -> LlmReply:
            raise RuntimeError("llm down")

    outcome = ReactRunner().run(_session(tmp_path, _Boom()))

    assert outcome.status == "failed"
    assert outcome.stop_reason == "llm_error"
    event = _events(tmp_path)[-1]
    assert event["type"] == "run.failed"
    assert event["stop_reason"] == "llm_error"
    assert "llm down" in event["error"]


def test_tool_exception_emits_run_failed(tmp_path: Path) -> None:
    llm = ScriptedLlm([_action("read", "read_file", {"path": "missing.txt"})])
    session = _session(tmp_path, llm)

    def _boom(name: str, args: dict) -> dict:
        raise RuntimeError("tool blew up")

    session.dispatch_tool = _boom  # type: ignore[method-assign]
    outcome = ReactRunner().run(session)

    assert outcome.status == "failed"
    assert outcome.stop_reason == "tool_error"
    assert llm.calls == 1
    event = _events(tmp_path)[-1]
    assert event["type"] == "run.failed"
    assert event["stop_reason"] == "tool_error"


def test_cancel_during_shell_emits_cancelled_without_another_llm(tmp_path: Path) -> None:
    import time

    root = tmp_path / "sandbox"
    root.mkdir(exist_ok=True)
    (root / "sleep.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    llm = ScriptedLlm([
        _action("sleep", "shell", {"argv": ["python3", "sleep.py"]}),
        _action("should not run", None, done=True),
    ])
    session = _session(tmp_path, llm)
    real_run = session.sandbox.run

    def run(argv: list[str], *, timeout_s: float | None = None):
        session.request_cancel()
        return real_run(argv, timeout_s=timeout_s)

    session.sandbox.run = run  # type: ignore[method-assign]
    started = time.monotonic()
    outcome = ReactRunner().run(session)

    assert outcome.status == "cancelled"
    assert outcome.stop_reason == "cancelled"
    assert llm.calls == 1
    assert time.monotonic() - started < 5
    assert _events(tmp_path)[-1] == {"type": "run.cancelled", "stop_reason": "cancelled"}
