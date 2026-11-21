"""Fake implementations of ports for tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from coding_agent.ports import CompletedProc
from coding_agent.proc_run import TrackedProcess


class FakeUsageMeter:
    def __init__(self) -> None:
        self._input = 0
        self._output = 0
        self._cost = 0.0

    def add_tokens(self, input_n: int, output_n: int) -> None:
        self._input += input_n
        self._output += output_n

    def tokens_used(self) -> int:
        return self._input + self._output

    def set_cost_usd(self, amount: float) -> None:
        self._cost = amount

    def cost_usd(self) -> float:
        return self._cost


class FakeSandbox:
    def __init__(self, root: Path, *, cancel: Callable[[], bool] | None = None) -> None:
        self._root = root.resolve()
        self._tracked = TrackedProcess()
        self._cancel = cancel

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
        return self._tracked.run(list(argv), self._root, timeout_s=timeout_s, cancel=self._cancel)

    def terminate(self) -> None:
        self._tracked.terminate()