"""Tracked subprocess runs with timeout and cancel polling."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from coding_agent.ports import CompletedProc

DEFAULT_COMMAND_TIMEOUT_S = 120.0
_POLL_S = 0.05
_KILL_GRACE_S = 2.0

_SCRUBBED_ENV_KEYS = frozenset({
    "LOOM_AGENT_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "TYPESAFE_API_KEY",
    "LOOM_AUTH_TOKEN",
})


def scrub_tool_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Drop API keys from the environment passed to tool subprocesses."""
    source = dict(os.environ if environ is None else environ)
    for key in _SCRUBBED_ENV_KEYS:
        source.pop(key, None)
    return source


class TrackedProcess:
    """One in-flight child. ``run`` replaces it; ``terminate`` kills it."""

    def __init__(self) -> None:
        self.child: subprocess.Popen[str] | None = None

    def run(self, argv: list[str], cwd: Path, *, timeout_s: float | None = None, cancel: Callable[[], bool] | None = None) -> CompletedProc:
        popen_kwargs: dict = {"start_new_session": True} if os.name != "nt" else {}
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=scrub_tool_env(),
            **popen_kwargs,
        )
        self.child = proc
        done = threading.Event()
        reason: list[str] = []
        watcher = threading.Thread(
            target=_watch,
            args=(proc, done, reason, timeout_s, cancel),
            name="loom-sandbox-watch",
            daemon=True,
        )
        watcher.start()
        try:
            stdout, stderr = proc.communicate()
        finally:
            done.set()
            watcher.join(timeout=1)
            if self.child is proc:
                self.child = None
        err = stderr or ""
        if reason:
            err = f"{err}\n{reason[0]}".strip() if err else reason[0]
        code = proc.returncode
        if code is None:
            code = -15 if reason[:1] == ["cancelled"] else 1
        return CompletedProc(returncode=code, stdout=stdout or "", stderr=err)

    def terminate(self) -> None:
        proc = self.child
        if proc is not None and proc.poll() is None:
            _kill(proc)


def _watch(proc: subprocess.Popen[str], done: threading.Event, reason: list[str], timeout_s: float | None, cancel: Callable[[], bool] | None) -> None:
    started = time.monotonic()
    while not done.wait(_POLL_S):
        if proc.poll() is not None:
            return
        if cancel is not None and cancel():
            reason.append("cancelled")
            _kill(proc)
            return
        if timeout_s is not None and (time.monotonic() - started) >= timeout_s:
            reason.append("timeout")
            _kill(proc)
            return


def _kill(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            proc.terminate()
    else:
        proc.terminate()
    deadline = time.monotonic() + _KILL_GRACE_S
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(_POLL_S)
    if proc.poll() is None:
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
        else:
            proc.kill()