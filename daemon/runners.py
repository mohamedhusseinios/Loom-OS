"""Agent runner registry — how the loom worker invokes each coding-agent CLI.

The worker is otherwise agent-agnostic (worktree, progress, commit, status are
generic). The only agent-specific knowledge is *how to invoke the CLI headlessly*
and *how to read its result*. That lives here as a declarative registry, so
adding an agent is a few lines of data rather than new control flow.

Output modes:
  - "stream-json": Claude only. Built and parsed in daemon.worker.run_claude
    (live progress, session_id, budget). build_argv is None here.
  - "stdout":      everyone else. Run the command, capture stdout as the result
    text; a non-zero exit code is an error. Handled by run_stdout().
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class AgentResult:
    """Neutral result returned by every runner. session_id is Claude-only."""
    text: str
    session_id: Optional[str]
    is_error: bool


@dataclass
class RunnerSpec:
    """Declarative description of how to run one agent CLI headlessly."""
    binary: str
    mode: str  # "stream-json" | "stdout"
    build_argv: Optional[Callable[[str], list[str]]] = None  # (prompt) -> argv after binary
    streams_progress: bool = False
    supports_resume: bool = False
    supports_budget: bool = False


# Canonical agent name -> RunnerSpec. Keys MUST match daemon.known_agents names
# and the suffix-stripped assignee in daemon.api._route_task_execution.
def _unsafe_runners_allowed() -> bool:
    return os.environ.get("LOOM_ALLOW_UNSAFE_RUNNERS", "").strip().lower() in {"1", "true", "yes"}


def _codex_argv(prompt: str) -> list[str]:
    if _unsafe_runners_allowed():
        return ["exec", "--dangerously-bypass-approvals-and-sandbox", prompt]
    return ["exec", prompt]


def _gemini_argv(prompt: str) -> list[str]:
    if _unsafe_runners_allowed():
        return ["-p", prompt, "--approval-mode", "yolo"]
    return ["-p", prompt]


def _copilot_argv(prompt: str) -> list[str]:
    if _unsafe_runners_allowed():
        return ["-p", prompt, "--allow-all-tools"]
    return ["-p", prompt]


def _aider_argv(prompt: str) -> list[str]:
    if _unsafe_runners_allowed():
        return ["--message", prompt, "--yes-always"]
    return ["--message", prompt]


RUNNERS: dict[str, RunnerSpec] = {
    "claude-code": RunnerSpec(
        binary="claude", mode="stream-json", build_argv=None,
        streams_progress=True, supports_resume=True, supports_budget=True,
    ),
    "hermes": RunnerSpec(
        binary="hermes", mode="stdout",
        build_argv=lambda prompt: ["-z", prompt],
    ),
    "codex": RunnerSpec(
        binary="codex", mode="stdout", build_argv=_codex_argv,
    ),
    "gemini-cli": RunnerSpec(
        binary="gemini", mode="stdout", build_argv=_gemini_argv,
    ),
    "copilot-cli": RunnerSpec(
        binary="copilot", mode="stdout", build_argv=_copilot_argv,
    ),
    "aider": RunnerSpec(
        binary="aider", mode="stdout", build_argv=_aider_argv,
    ),
    "loom-agent": RunnerSpec(
        binary=sys.executable, mode="stdout",
        build_argv=lambda prompt: (
            ["-m", "daemon.agent_run", "--manifest", os.environ["LOOM_AGENT_MANIFEST"]]
            if os.environ.get("LOOM_AGENT_MANIFEST")
            else ["-m", "daemon.agent_run", "--prompt", prompt]
        ),
    ),
}


def runnable_agents() -> set[str]:
    """Canonical names of agents the daemon can spawn a worker for."""
    return set(RUNNERS)


DEFAULT_STDOUT_TIMEOUT_S = float(os.environ.get("LOOM_STDOUT_TIMEOUT_S", "1800"))


def run_stdout(
    spec: RunnerSpec,
    prompt: str,
    cwd: str,
    on_progress: Optional[Callable[[str], None]] = None,
    timeout_s: float | None = None,
) -> AgentResult:
    """Run a plain-stdout agent CLI to completion in ``cwd``.

    Captures stdout as the result text; a non-zero exit marks an error (falling
    back to stderr for the message when stdout is empty). ``timeout_s`` (or
    ``LOOM_STDOUT_TIMEOUT_S``, default 1800) kills runaway non-Claude agents
    that ignore ``--max-budget-usd``.
    """
    if spec.build_argv is None:
        raise ValueError(f"{spec.binary}: stdout runner requires build_argv")
    argv = [spec.binary, *spec.build_argv(prompt)]
    if on_progress:
        on_progress(f"Running {spec.binary}…")
    limit = DEFAULT_STDOUT_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as exc:
        msg = f"{spec.binary} exceeded timeout ({limit}s)"
        if on_progress:
            on_progress(msg)
        return AgentResult(text=msg, session_id=None, is_error=True)
    text = (proc.stdout or "").strip()
    if proc.returncode != 0:
        msg = text or (proc.stderr or "").strip() or f"{spec.binary} exited non-zero"
        return AgentResult(text=msg, session_id=None, is_error=True)
    return AgentResult(text=text, session_id=None, is_error=False)
