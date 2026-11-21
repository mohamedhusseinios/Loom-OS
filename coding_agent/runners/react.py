"""ReAct loop: one JSON action per model turn."""

from __future__ import annotations

import json
from typing import Any

from coding_agent.runners.base import RunOutcome, RunStatus, TurnResult
from coding_agent.session import BudgetExceeded, RunCancelled, RunSession

_SYSTEM = (
    "Reply with one JSON object and nothing else: "
    '{"thought": string, "tool": string or null, "args": object, "done": boolean}.'
)

_EVENT_TYPE = {
    "succeeded": "run.succeeded",
    "failed": "run.failed",
    "cancelled": "run.cancelled",
}


class ReactRunner:
    def run(self, session: RunSession) -> RunOutcome:
        messages = _initial_messages(session)
        while True:
            try:
                session.check_can_continue()
            except BudgetExceeded as exc:
                return _finish(session, "failed", f"budget_{exc.reason}")
            except RunCancelled as exc:
                return _finish(session, "cancelled", exc.reason)

            reply = session.llm.chat(messages, model=_model(session))
            session.meter.add_tokens(reply.input_tokens, reply.output_tokens)
            session.record_step()
            try:
                action = _parse_action(reply.content)
            except (json.JSONDecodeError, ValueError):
                return _finish(session, "failed", "invalid_action")

            session.events.emit(
                {
                    "type": "llm.action",
                    "thought": action.thought,
                    "tool": action.tool,
                    "done": action.done,
                }
            )
            result: dict[str, Any] | None = None
            if action.tool:
                result = session.dispatch_tool(action.tool, action.args)
                session.events.emit({"type": "tool.result", "tool": action.tool, "result": result})
            if action.done:
                return _finish(session, "succeeded", "done")

            messages.append({"role": "assistant", "content": reply.content})
            messages.append({"role": "user", "content": _observation(action.tool, result)})


def _parse_action(content: str) -> TurnResult:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("action must be a JSON object")
    thought = data.get("thought", "")
    if not isinstance(thought, str):
        raise ValueError("thought must be a string")
    tool = data.get("tool")
    if tool is not None and not isinstance(tool, str):
        raise ValueError("tool must be a string or null")
    if tool == "":
        tool = None
    args = data.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    done = data.get("done", False)
    if not isinstance(done, bool):
        raise ValueError("done must be a bool")
    return TurnResult(thought=thought, tool=tool, args=args, done=done)


def _initial_messages(session: RunSession) -> list[dict[str, Any]]:
    prompt = session.manifest.get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt)
    packed = session.context.pack()
    parts = [part for part in (packed, prompt) if part]
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _model(session: RunSession) -> str:
    model = session.manifest.get("model", "")
    return model if isinstance(model, str) else str(model)


def _observation(tool: str | None, result: dict[str, Any] | None) -> str:
    if tool is None:
        return "No tool was called."
    return json.dumps({"tool": tool, "result": result}, ensure_ascii=False)


def _finish(session: RunSession, status: RunStatus, stop_reason: str) -> RunOutcome:
    session.events.emit({"type": _EVENT_TYPE[status], "stop_reason": stop_reason})
    return RunOutcome(status=status, stop_reason=stop_reason)
