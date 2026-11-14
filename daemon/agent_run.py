"""CLI entry for loom-agent worker runs (stdout mode).

Invoked as: ``python -m daemon.agent_run --prompt "..."``

Resolves the LLM key from (in order):
1. ``LOOM_AGENT_API_KEY`` / ``DEEPSEEK_API_KEY`` env
2. Dashboard Agent settings in ``~/.loom/state.db`` (BYOK)

Prints the model response to stdout for the worker to capture.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

from daemon.llm_client import LlmClient, LlmError, DEFAULT_MODEL, DEFAULT_BASE_URL


def _settings_db_path() -> str:
    return os.path.expanduser(os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))


def load_llm_config_from_settings(db_path: str | None = None) -> tuple[str, str, str]:
    """Return ``(api_key, base_url, model)`` from agent_settings, or empty key."""
    path = db_path or _settings_db_path()
    if not os.path.exists(path):
        return "", DEFAULT_BASE_URL, DEFAULT_MODEL
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT default_model, providers_json, api_keys_json FROM agent_settings WHERE id = 1"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return "", DEFAULT_BASE_URL, DEFAULT_MODEL
    if row is None:
        return "", DEFAULT_BASE_URL, DEFAULT_MODEL
    model = row["default_model"] or DEFAULT_MODEL
    keys = json.loads(row["api_keys_json"] or "{}")
    providers = json.loads(row["providers_json"] or "[]")
    base_url = DEFAULT_BASE_URL
    api_key = keys.get("deepseek") or ""
    for p in providers:
        if not isinstance(p, dict):
            continue
        pid = p.get("id") or ""
        models = p.get("model_ids") or []
        if model in models or pid == "deepseek":
            base_url = p.get("base_url") or base_url
            api_key = keys.get(pid) or api_key
            if model in models:
                break
    return api_key or "", base_url, model


def resolve_llm_config() -> tuple[str, str, str]:
    """Env overrides settings DB (for supervisor-injected keys)."""
    db_key, db_base, db_model = load_llm_config_from_settings()
    api_key = (
        os.environ.get("LOOM_AGENT_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or db_key
    )
    base_url = os.environ.get("LOOM_AGENT_BASE_URL") or db_base
    model = os.environ.get("LOOM_AGENT_MODEL") or db_model
    return api_key, base_url, model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loom agent worktree runner")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

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
