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
from datetime import datetime, timezone

from daemon.worktree import create_worktree, commit_all, current_branch
from daemon.runners import AgentResult, RUNNERS, run_stdout

logger = logging.getLogger("loom.worker")

# Back-compat alias: run_claude still returns this; tests import ClaudeResult.
ClaudeResult = AgentResult


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
    if code != 0:
        # Any non-zero exit is a failure (e.g. budget exhausted). Keep the
        # result text if one was emitted; otherwise fall back to stderr
        # (empty string is falsy, so the default kicks in when stderr is empty).
        final["is_error"] = True
        if not final["text"]:
            final["text"] = (proc.stderr.read() or "claude exited non-zero").strip()
    return ClaudeResult(final["text"], final["session_id"], final["is_error"])


def run_agent(agent, prompt, cwd, model=None, max_budget_usd=5.0,
              resume=None, on_progress=None) -> AgentResult:
    """Dispatch to the right runner for ``agent`` (a canonical name).

    Claude keeps its rich stream-json path (run_claude); every other registered
    agent runs through the generic stdout runner. Unknown agents raise — the API
    spawn gate (daemon.api.LOOM_WORKER_AGENTS) only routes registered agents here.
    """
    if agent == "claude-code":
        return run_claude(prompt, cwd, model=model,
                          max_budget_usd=max_budget_usd, resume=resume,
                          on_progress=on_progress)
    spec = RUNNERS.get(agent)
    if spec is None:
        raise ValueError(f"no runner for agent {agent!r}")
    return run_stdout(spec, prompt, cwd, on_progress=on_progress)


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

    def _api(self, method: str, path: str, body: dict | None = None) -> dict | list:
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

    def _post_progress(self, task_id: str, message: str, kind: str = "text") -> None:
        try:
            self._api("POST", f"/api/projects/{self.project}/tasks/{task_id}/progress",
                      {"message": message, "kind": kind})
        except Exception:
            pass  # progress is best-effort

    def _write_finding(self, task_id: str, title: str, text: str) -> None:
        inbox = os.path.expanduser(f"~/.loom/inbox/{self.project}")
        os.makedirs(inbox, exist_ok=True)
        fid = uuid.uuid4().hex[:8]
        ts = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(inbox, f"finding-{fid}.md"), "w", encoding="utf-8") as f:
            f.write(
                f"---\nagent: {self.agent}\nproject: {self.project}\n"
                f"task_id: {task_id}\ntype: general\ntimestamp: {ts}\n---\n"
                f"# Task complete: {title}\n\n{text}\n"
            )

    def process_task(self, task: dict) -> None:
        task_id = task["id"]
        title = task.get("title", "")
        instruction = task.get("instruction", "")
        criteria = task.get("acceptance_criteria") or ""
        branch = f"loom/task-{task_id}"
        workspace = os.path.join(self.workspaces_dir, self.project, f"task-{task_id}")

        # current_branch() + create_worktree() both require a git repo; a
        # misconfigured project_path must block the task, not crash the loop.
        try:
            base_branch = current_branch(self.project_path)
            create_worktree(self.project_path, workspace, branch, base_ref=base_branch)
        except RuntimeError as exc:
            self._post_progress(task_id, f"Worktree failed: {exc}", kind="error")
            self._patch_task(task_id, {
                "status": "blocked",
                "result": json.dumps({"branch": branch, "base_branch": "unknown",
                                      "error": f"worktree failed: {exc}"}),
            })
            return

        meta = {"branch": branch, "base_branch": base_branch}

        self._patch_task(task_id, {"workspace_path": workspace})
        self._post_progress(task_id, f"Created worktree on {branch}", kind="milestone")

        prompt = instruction
        if criteria:
            prompt = f"{instruction}\n\nAcceptance criteria:\n{criteria}"

        resume = None
        try:
            prior = json.loads(task.get("result") or "{}")
            resume = prior.get("session_id")
        except (ValueError, TypeError):
            resume = None

        self._post_progress(task_id, "Agent started", kind="milestone")
        result = run_agent(
            self.agent, prompt, cwd=workspace, model=self.model,
            max_budget_usd=self.max_budget_usd, resume=resume,
            on_progress=lambda line: self._post_progress(
                task_id, line, kind="tool" if line.startswith("tool:") else "text"),
        )

        meta["summary"] = result.text
        meta["session_id"] = result.session_id

        if result.is_error:
            meta["error"] = result.text or "claude reported an error"
            self._post_progress(task_id, meta["error"], kind="error")
            self._patch_task(task_id, {
                "status": "blocked", "result": json.dumps(meta),
                "workspace_path": workspace,
            })
            return

        commit_all(workspace, f"loom task {task_id}: {title}")
        self._write_finding(task_id, title, result.text)
        self._post_progress(task_id, result.text or "(no output)", kind="summary")
        self._post_progress(task_id, "Task complete", kind="milestone")
        self._patch_task(task_id, {
            "status": "done", "result": json.dumps(meta),
            "workspace_path": workspace,
        })

    def poll_once(self) -> None:
        for task in self.eligible(self._get_running_tasks()):
            self._inflight.add(task["id"])
            try:
                self.process_task(task)
            finally:
                self._inflight.discard(task["id"])
            return  # one task per tick (V1)

    def run_once(self, task_id: str) -> None:
        """Process a single eligible Running task by id, then return (no poll loop)."""
        self.ensure_registered()
        task = next(
            (t for t in self.eligible(self._get_running_tasks()) if t.get("id") == task_id),
            None,
        )
        if task is None:
            logger.info("task %s not eligible for %s; nothing to do", task_id, self.agent_id)
            return
        self.process_task(task)

    def _heartbeat(self) -> None:
        inbox = os.path.expanduser(f"~/.loom/inbox/{self.project}")
        os.makedirs(inbox, exist_ok=True)
        with open(os.path.join(inbox, "heartbeat.json"), "w") as f:
            json.dump({
                "agent": self.agent,
                "project": self.project,
                "status": "online",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f)

    def run(self) -> None:
        self.ensure_registered()
        logger.info("worker %s online for project %s", self.agent_id, self.project)
        last_hb = 0.0
        while not self._stop:
            now = time.monotonic()
            if now - last_hb > 30:
                try:
                    self._heartbeat()
                except Exception as exc:
                    logger.warning("heartbeat failed: %s", exc)
                last_hb = now
            try:
                self.poll_once()
            except Exception as exc:  # never let the loop die
                logger.warning("poll error: %s", exc)
            time.sleep(self.poll_interval)

    def ensure_registered(self) -> None:
        try:
            resp = self._api("GET", f"/api/projects/{self.project}/agents")
            agents = resp.get("agents", []) if isinstance(resp, dict) else (resp or [])
        except Exception:
            agents = []
        if self.agent_id not in {a.get("agent_id") for a in agents}:
            self._api("POST", f"/api/projects/{self.project}/register-agent", {
                "agent": self.agent, "version": "1.0",
                "project_path": self.project_path, "capabilities": ["task-execution"],
            })
