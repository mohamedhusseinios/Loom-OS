"""loom worker — autonomously runs Claude Code on Running tasks.

A first-party Loom process (not a third-party agent): it talks to the
daemon over HTTP, runs `claude -p` headless in an isolated git worktree,
and writes results + findings back. Single task at a time (V1).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from daemon.worktree import create_worktree, commit_all, current_branch

logger = logging.getLogger("loom.worker")


@dataclass
class ClaudeResult:
    text: str
    session_id: str | None
    is_error: bool


def _summarize_event(event: dict) -> str:
    """One-line progress string from an assistant/tool stream event."""
    msg = event.get("message", {})
    for block in msg.get("content", []) if isinstance(msg, dict) else []:
        if block.get("type") == "tool_use":
            return f"tool: {block.get('name', '?')}"
        if block.get("type") == "text":
            return block.get("text", "")[:120]
    return "working…"


def run_claude(prompt, cwd, model=None, max_budget_usd=5.0, resume=None, on_progress=None) -> ClaudeResult:
    """Run `claude -p` headless and return a ClaudeResult.

    Uses --max-budget-usd to cap autonomous spend per run. The installed
    claude CLI (2.1.190) does not support --max-turns.
    """
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "acceptEdits",
        "--max-budget-usd", str(max_budget_usd),
    ]
    if model:
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]

    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    final = {"text": "", "session_id": None, "is_error": False}
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            final["text"] = event.get("result", "") or ""
            final["session_id"] = event.get("session_id")
            final["is_error"] = bool(event.get("is_error"))
        elif event.get("type") == "assistant" and on_progress:
            on_progress(_summarize_event(event))
    code = proc.wait()
    if code != 0 and not final["text"]:
        final["is_error"] = True
        final["text"] = (proc.stderr.read() or "claude exited non-zero").strip()
    return ClaudeResult(final["text"], final["session_id"], final["is_error"])


class Worker:
    def __init__(
        self,
        project: str,
        agent: str,
        project_path: str,
        base_url: str = "http://127.0.0.1:8472",
        model: str | None = None,
        max_budget_usd: float = 5.0,
        poll_interval: float = 2.5,
    ):
        self.project = project
        self.agent = agent
        self.project_path = project_path
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_budget_usd = max_budget_usd
        self.poll_interval = poll_interval
        self.workspaces_dir: str = os.path.expanduser("~/.loom/workspaces")
        self._inflight: set[str] = set()
        self._stop: bool = False

    @property
    def agent_id(self) -> str:
        return f"{self.agent}-{self.project}"

    def eligible(self, tasks: list[dict]) -> list[dict]:
        return [
            t for t in tasks
            if t.get("assignee") == self.agent_id and t.get("id") not in self._inflight
        ]

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")

    def _get_running_tasks(self) -> list[dict]:
        return self._api("GET", f"/api/projects/{self.project}/tasks?status=running")

    def _patch_task(self, task_id: str, body: dict) -> dict:
        return self._api("PATCH", f"/api/projects/{self.project}/tasks/{task_id}", body)

    def _post_progress(self, task_id: str, message: str) -> None:
        try:
            self._api("POST", f"/api/projects/{self.project}/tasks/{task_id}/progress",
                      {"message": message})
        except Exception:
            pass  # progress is best-effort

    def _write_finding(self, task_id: str, title: str, text: str) -> None:
        inbox = os.path.expanduser(f"~/.loom/inbox/{self.project}")
        os.makedirs(inbox, exist_ok=True)
        fid = uuid.uuid4().hex[:8]
        ts = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(inbox, f"finding-{fid}.md"), "w") as f:
            f.write(
                f"---\nagent: {self.agent}\nproject: {self.project}\n"
                f"type: general\ntimestamp: {ts}\n---\n"
                f"# Task complete: {title}\n\n{text}\n"
            )

    def ensure_registered(self) -> None:
        try:
            agents = self._api("GET", f"/api/projects/{self.project}/agents")
        except Exception:
            agents = []
        if self.agent_id not in {a.get("agent_id") for a in agents}:
            self._api("POST", f"/api/projects/{self.project}/register-agent", {
                "agent": self.agent, "version": "1.0",
                "project_path": self.project_path,
                "capabilities": ["task-execution"],
            })
