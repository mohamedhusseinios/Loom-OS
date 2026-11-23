"""CLI entry for loom-agent worker runs (stdout mode).

Invoked as:

- ``python -m daemon.agent_run --prompt "..."`` — legacy single-shot chat
- ``python -m daemon.agent_run --manifest PATH`` — coding_agent ReAct loop

``--prompt`` is optional when ``--manifest`` is set. A manifest may include
``run_dir``, ``events_path``, ``prompt``, budgets, and ``cancel_path``.
Events are appended to ``events_path`` or ``run_dir/events.jsonl``.

Resolves the LLM key from (in order):
1. ``LOOM_AGENT_API_KEY`` / ``DEEPSEEK_API_KEY`` env
2. Dashboard Agent settings in ``~/.loom/state.db`` (BYOK)

Prints the model response (single-shot) or ``status: stop_reason`` (loop)
to stdout for the worker to capture.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from coding_agent.events import JsonlEventSink
from coding_agent.runners.react import ReactRunner
from coding_agent.session import RunSession
from daemon.agent_credentials import DEEPSEEK_PROVIDER_ID
from daemon.coding_adapters import LlmClientAdapter, SimpleUsageMeter, StubContextSource, WorktreeSandbox
from daemon.llm_client import LlmClient, LlmError


def _settings_db_path() -> str:
    return os.path.expanduser(os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))


def load_llm_config_from_settings(db_path: str | None = None) -> tuple[str, str, str, str]:
    """Return ``(api_key, base_url, model, provider_id)`` from agent_settings, or empty key."""
    from daemon.agent_credentials import load_stored_credentials
    creds = load_stored_credentials(db_path or _settings_db_path())
    return creds.llm_from_stored()


def resolve_llm_config() -> tuple[str, str, str]:
    """Match chat: dashboard settings first, then LOOM_AGENT_*/DEEPSEEK_* env."""
    db_key, db_base, db_model, db_provider = load_llm_config_from_settings()
    provider_id = os.environ.get("LOOM_AGENT_PROVIDER") or db_provider
    api_key = db_key or os.environ.get("LOOM_AGENT_API_KEY") or ""
    # DeepSeek env creds are only valid for DeepSeek; never send them to a custom endpoint.
    if not api_key and provider_id == DEEPSEEK_PROVIDER_ID:
        api_key = os.environ.get("DEEPSEEK_API_KEY") or ""
    base_url = os.environ.get("LOOM_AGENT_BASE_URL") or db_base
    model = os.environ.get("LOOM_AGENT_MODEL") or db_model
    return api_key, base_url, model


def _events_path(manifest: dict, manifest_file: Path) -> Path:
    explicit = manifest.get("events_path")
    if isinstance(explicit, str) and explicit:
        return Path(explicit)
    run_dir = manifest.get("run_dir")
    if isinstance(run_dir, str) and run_dir:
        return Path(run_dir) / "events.jsonl"
    return manifest_file.parent / "events.jsonl"


_TERMINAL_TYPES = frozenset({"run.succeeded", "run.failed", "run.cancelled"})


def events_have_terminal(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") in _TERMINAL_TYPES:
            return True
    return False


def ensure_terminal_event(path: Path, event_type: str, stop_reason: str) -> bool:
    """Append a terminal event when the JSONL sink does not already have one."""
    if event_type not in _TERMINAL_TYPES or events_have_terminal(path):
        return False
    JsonlEventSink(path).emit({"type": event_type, "stop_reason": stop_reason})
    return True


def seal_manifest_run(manifest_path: str, *, stop_reason: str = "worker_exit") -> None:
    """Close a manifest run that exited without a terminal JSONL event."""
    manifest_file = Path(manifest_path)
    try:
        loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(loaded, dict):
        return
    events_path = _events_path(loaded, manifest_file)
    cancel_path = loaded.get("cancel_path")
    if isinstance(cancel_path, str) and cancel_path and Path(cancel_path).is_file():
        ensure_terminal_event(events_path, "run.cancelled", "cancelled")
        return
    ensure_terminal_event(events_path, "run.failed", stop_reason)


def _worktree_root(manifest: dict) -> Path:
    for key in ("worktree", "worktree_path"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return Path(value)
    return Path.cwd()


def _manifest_family_id(manifest: dict) -> str:
    raw = manifest.get("family_id", "react")
    return raw if isinstance(raw, str) else "react"


def _should_emit_runner_fallback(manifest: dict) -> bool:
    family_id = _manifest_family_id(manifest)
    return family_id != "react" or manifest.get("runner_fallback") is True


def run_manifest(path: str, *, prompt: str | None = None, model: str | None = None) -> int:
    """Load a JSON run manifest and execute the ReAct loop."""
    manifest_file = Path(path)
    try:
        loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not isinstance(loaded, dict):
        print("manifest must be a JSON object", file=sys.stderr)
        return 1

    manifest = dict(loaded)
    if prompt and not manifest.get("prompt"):
        manifest["prompt"] = prompt
    api_key, base_url, resolved_model = resolve_llm_config()
    if model:
        resolved_model = model
    if not manifest.get("model"):
        manifest["model"] = resolved_model

    events_path = _events_path(manifest, manifest_file)
    event_sink = JsonlEventSink(events_path)
    if _should_emit_runner_fallback(manifest):
        event_sink.emit({
            "type": "strategy.runner_fallback",
            "family_id": _manifest_family_id(manifest),
            "executed_runner": "react",
        })
    try:
        client = LlmClient(api_key=api_key, base_url=base_url)
        session = RunSession(
            manifest,
            WorktreeSandbox(_worktree_root(manifest)),
            event_sink,
            LlmClientAdapter(client),
            SimpleUsageMeter(),
            StubContextSource(),
        )
        outcome = ReactRunner().run(session)
    except Exception as exc:
        reason = "llm_error" if isinstance(exc, LlmError) else "worker_exit"
        ensure_terminal_event(events_path, "run.failed", reason)
        print(str(exc), file=sys.stderr)
        return 1
    if outcome.error:
        print(outcome.error, file=sys.stderr)
    print(f"{outcome.status}: {outcome.stop_reason}")
    return 0 if outcome.status in ("succeeded", "cancelled") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loom agent worktree runner")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    if args.manifest:
        return run_manifest(args.manifest, prompt=args.prompt, model=args.model)
    if not args.prompt:
        parser.error("--prompt is required unless --manifest is set")

    api_key, base_url, model = resolve_llm_config()
    if args.model:
        model = args.model
    client = LlmClient(api_key=api_key, base_url=base_url)
    messages = [
        {
            "role": "system",
            "content": (
                "You are the Loom coding agent running in a git worktree. "
                "Implement the task. Summarize what you would change; "
                "prefer concrete file-level guidance."
            ),
        },
        {"role": "user", "content": args.prompt},
    ]
    try:
        text = client.chat(messages, model=model)
    except LlmError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
