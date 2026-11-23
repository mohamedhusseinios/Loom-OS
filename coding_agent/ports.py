"""Port protocols and shared value types for the coding agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class CompletedProc:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class LlmReply:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class Sandbox(Protocol):
    def root(self) -> Path: ...
    def read_text(self, rel: str) -> str: ...
    def write_text(self, rel: str, content: str) -> None: ...
    def run(self, argv: list[str], *, timeout_s: float | None = None) -> CompletedProc: ...


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: dict) -> None: ...


@runtime_checkable
class UsageMeter(Protocol):
    def add_tokens(self, input_n: int, output_n: int) -> None: ...
    def tokens_used(self) -> int: ...
    def cost_usd(self) -> float: ...


@runtime_checkable
class LlmPort(Protocol):
    def chat(self, messages: list[dict], *, model: str) -> LlmReply: ...


@runtime_checkable
class ContextSource(Protocol):
    def pack(self) -> str: ...