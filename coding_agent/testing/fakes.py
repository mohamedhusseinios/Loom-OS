"""Fake implementations of ports for tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from coding_agent.ports import CompletedProc


class FakeSandbox:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

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
        completed = subprocess.run(
            argv,
            cwd=self._root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return CompletedProc(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )