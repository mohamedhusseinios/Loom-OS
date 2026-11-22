"""Daemon-side adapters for the coding_agent loop.

`coding_agent` stays free of daemon imports. This module is the glue:
a worktree sandbox, an LLM port over ``daemon.llm_client``, a token meter,
and a context stub.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from coding_agent.ports import CompletedProc, LlmReply
from coding_agent.proc_run import DEFAULT_COMMAND_TIMEOUT_S, TrackedProcess
from daemon.llm_client import LlmClient


class WorktreeSandbox:
    """Sandbox whose root is the worker worktree (typically the process cwd)."""

    def __init__(self, root: Path | str | None = None, *, cancel: Callable[[], bool] | None = None, command_timeout_s: float | None = DEFAULT_COMMAND_TIMEOUT_S) -> None:
        self._root = Path(root if root is not None else Path.cwd()).resolve()
        self._tracked = TrackedProcess()
        self._cancel = cancel
        self._command_timeout_s = command_timeout_s

    def bind_cancel(self, cancel: Callable[[], bool] | None) -> None:
        self._cancel = cancel

    def root(self) -> Path:
        return self._root

    def _resolve_under_root(self, rel: str) -> Path:
        target = (self._root / rel).resolve()
        if target != self._root and self._root not in target.parents:
            raise ValueError(f"path escapes sandbox root: {rel!r}")
        return target

    def read_text(self, rel: str) -> str:
        return self._resolve_under_root(rel).read_text(encoding="utf-8")

    def write_text(self, rel: str, content: str) -> None:
        path = self._resolve_under_root(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run(self, argv: list[str], *, timeout_s: float | None = None) -> CompletedProc:
        limit = self._command_timeout_s if timeout_s is None else timeout_s
        return self._tracked.run(list(argv), self._root, timeout_s=limit, cancel=self._cancel)

    def terminate(self) -> None:
        self._tracked.terminate()


class LlmClientAdapter:
    """Wrap ``daemon.llm_client.LlmClient`` as a coding_agent ``LlmPort``."""

    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def chat(self, messages: list[dict], *, model: str) -> LlmReply:
        content = self._client.chat(messages, model=model or "deepseek-chat")
        usage = self._client.last_usage or {}
        input_n = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_n = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        return LlmReply(content=content, input_tokens=input_n, output_tokens=output_n)


class SimpleUsageMeter:
    def __init__(self) -> None:
        self._input = 0
        self._output = 0

    def add_tokens(self, input_n: int, output_n: int) -> None:
        self._input += int(input_n)
        self._output += int(output_n)

    def tokens_used(self) -> int:
        return self._input + self._output

    def cost_usd(self) -> float:
        return 0.0


class StubContextSource:
    def pack(self) -> str:
        return ""
