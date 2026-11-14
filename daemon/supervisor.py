"""Worker supervisor — spawns and tracks one-shot `loom worker` subprocesses.

One subprocess per task (V1): the daemon launches a worker that processes a
single Running task and exits. The supervisor keeps the live handle so the UI
can show "a worker is attached" and offer Stop. Exited processes are reaped
lazily on inspection (no background task), which keeps test mode side-effect free.
"""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger("loom.supervisor")


class WorkerSupervisor:
    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}

    def spawn(self, project: str, agent: str, project_path: str,
              task_id: str, max_budget_usd: float = 5.0) -> None:
        """Launch a one-shot worker for a single task. No-op if already live."""
        if self.is_running(task_id):
            return
        cmd = [
            sys.executable, "-m", "daemon.main", "worker",
            "--once", "--task", task_id,
            "--project", project, "--agent", agent,
            "--project-path", project_path,
            "--max-budget-usd", str(max_budget_usd),
        ]
        logger.info("spawning one-shot worker for task %s", task_id)
        env = None
        if agent == "loom-agent":
            env = self._loom_agent_env()
        self._procs[task_id] = subprocess.Popen(cmd, env=env)

    @staticmethod
    def _loom_agent_env() -> dict[str, str]:
        """Pass dashboard BYOK keys into the loom-agent worker process."""
        import os
        env = os.environ.copy()
        try:
            from daemon.agent_run import load_llm_config_from_settings
            api_key, base_url, model = load_llm_config_from_settings()
        except Exception:
            return env
        if api_key and not env.get("LOOM_AGENT_API_KEY") and not env.get("DEEPSEEK_API_KEY"):
            env["LOOM_AGENT_API_KEY"] = api_key
            env["DEEPSEEK_API_KEY"] = api_key
        if base_url and not env.get("LOOM_AGENT_BASE_URL"):
            env["LOOM_AGENT_BASE_URL"] = base_url
        if model and not env.get("LOOM_AGENT_MODEL"):
            env["LOOM_AGENT_MODEL"] = model
        return env

    def is_running(self, task_id: str) -> bool:
        proc = self._procs.get(task_id)
        if proc is None:
            return False
        if proc.poll() is None:
            return True
        self._procs.pop(task_id, None)  # exited — reap
        return False

    def running_ids(self) -> list[str]:
        return [tid for tid in list(self._procs) if self.is_running(tid)]

    def stop(self, task_id: str) -> bool:
        """Terminate a live worker. Returns True if one was running."""
        proc = self._procs.get(task_id)
        if proc is None or proc.poll() is not None:
            self._procs.pop(task_id, None)
            return False
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        self._procs.pop(task_id, None)
        return True
