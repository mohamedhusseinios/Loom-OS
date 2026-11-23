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
        self._exited: set[str] = set()

    def _note_exit(self, task_id: str) -> None:
        self._procs.pop(task_id, None)
        self._exited.add(task_id)

    def exited_task_ids(self) -> set[str]:
        for task_id in list(self._procs):
            self.is_running(task_id)
        return set(self._exited)

    def forget_exited(self, task_ids: set[str]) -> None:
        self._exited.difference_update(task_ids)

    def spawn(self, project: str, agent: str, project_path: str, task_id: str, max_budget_usd: float = 5.0, manifest_path: str | None = None) -> None:
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
            env = self._loom_agent_env(manifest_path)
        self._procs[task_id] = subprocess.Popen(cmd, env=env)

    @staticmethod
    def _loom_agent_env(manifest_path: str | None = None) -> dict[str, str]:
        """Pass BYOK keys and this run's manifest into one worker process."""
        import os
        env = os.environ.copy()
        env.pop("LOOM_AGENT_MANIFEST", None)
        if manifest_path:
            env["LOOM_AGENT_MANIFEST"] = manifest_path
        try:
            from daemon.agent_run import load_llm_config_from_settings
            api_key, base_url, model, api_style, provider_id = load_llm_config_from_settings()
        except Exception:
            return env
        env["LOOM_AGENT_PROVIDER"] = provider_id
        if provider_id != "deepseek":
            # Non-DeepSeek endpoint: only its own stored key (possibly none); never the DeepSeek credential.
            env.pop("DEEPSEEK_API_KEY", None)
            env.pop("LOOM_AGENT_API_KEY", None)
        # Dashboard BYOK wins over process-level provider env, matching chat.
        if api_key:
            env["LOOM_AGENT_API_KEY"] = api_key
            if provider_id == "deepseek":
                env["DEEPSEEK_API_KEY"] = api_key
            elif provider_id == "openai":
                env["OPENAI_API_KEY"] = api_key
            elif provider_id == "anthropic":
                env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env["LOOM_AGENT_BASE_URL"] = base_url
        if model:
            env["LOOM_AGENT_MODEL"] = model
        if api_style:
            env["LOOM_AGENT_API_STYLE"] = api_style
        return env

    def is_running(self, task_id: str) -> bool:
        proc = self._procs.get(task_id)
        if proc is None:
            return False
        if proc.poll() is None:
            return True
        self._note_exit(task_id)
        return False

    def running_ids(self) -> list[str]:
        return [tid for tid in list(self._procs) if self.is_running(tid)]

    def stop(self, task_id: str) -> bool:
        """Terminate a live worker. Returns True if one was running."""
        proc = self._procs.get(task_id)
        if proc is None:
            return False
        if proc.poll() is not None:
            self._note_exit(task_id)
            return False
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        self._note_exit(task_id)
        return True
