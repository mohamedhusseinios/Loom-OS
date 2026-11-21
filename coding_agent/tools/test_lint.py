"""Run configured test and lint commands from the run manifest."""

from __future__ import annotations

from coding_agent.ports import CompletedProc, Sandbox


def run_tests(sandbox: Sandbox, manifest: dict) -> dict:
    return _run_manifest_command(sandbox, manifest, "test_command", "missing_test_command")


def run_lint(sandbox: Sandbox, manifest: dict) -> dict:
    return _run_manifest_command(sandbox, manifest, "lint_command", "missing_lint_command")


def _run_manifest_command(sandbox: Sandbox, manifest: dict, key: str, missing_reason: str) -> dict:
    argv = manifest.get(key)
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        return {"ok": False, "need_approval": False, "reason": missing_reason}
    try:
        proc = sandbox.run(list(argv))
    except OSError as exc:
        return {"ok": False, "need_approval": False, "reason": "spawn_failed", "stderr": str(exc)}
    return _from_proc(proc)


def _from_proc(proc: CompletedProc) -> dict:
    return {"ok": proc.returncode == 0, "need_approval": False, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
