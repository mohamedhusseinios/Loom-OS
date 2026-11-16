"""CLI entry for loom-agent worker runs (stdout mode).

Invoked as: ``python -m daemon.agent_run --prompt "..."``

Resolves the LLM key from (in order):
1. Dashboard Agent settings in ``~/.loom/state.db`` (BYOK)
2. ``LOOM_AGENT_API_KEY`` / provider-specific env

Prints the model response to stdout for the worker to capture.
"""

from __future__ import annotations

import argparse
import os
import sys

from daemon.agent_credentials import resolve_chat_key
from daemon.llm_client import LlmError, build_llm_client


def _settings_db_path() -> str:
    return os.path.expanduser(os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))


def load_llm_config_from_settings(db_path: str | None = None) -> tuple[str, str, str, str, str]:
    """Return ``(api_key, base_url, model, api_style, provider_id)`` from agent_settings."""
    from daemon.agent_credentials import load_stored_credentials
    creds = load_stored_credentials(db_path or _settings_db_path())
    api_key, base_url, model, api_style = creds.llm_from_stored()
    return api_key, base_url, model, api_style, creds.active_chat_provider_id()


def resolve_llm_config() -> tuple[str, str, str, str]:
    """Match chat: dashboard settings first, then LOOM_AGENT_*/provider env."""
    db_key, db_base, db_model, db_style, provider_id = load_llm_config_from_settings()
    api_key = resolve_chat_key(provider_id, db_key)
    base_url = os.environ.get("LOOM_AGENT_BASE_URL") or db_base
    model = os.environ.get("LOOM_AGENT_MODEL") or db_model
    api_style = os.environ.get("LOOM_AGENT_API_STYLE") or db_style
    return api_key, base_url, model, api_style


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loom agent worktree runner")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    api_key, base_url, model, api_style = resolve_llm_config()
    if args.model:
        model = args.model
    client = build_llm_client(api_key=api_key, base_url=base_url, api_style=api_style)
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
