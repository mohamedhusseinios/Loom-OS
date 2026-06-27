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
        self._procs[task_id] = subprocess.Popen(cmd)

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
