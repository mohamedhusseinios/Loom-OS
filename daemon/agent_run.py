"""CLI entry for loom-agent worker runs (stdout mode).

Invoked as: ``python -m daemon.agent_run --prompt "..."``

Resolves the LLM key from (in order):
1. ``LOOM_AGENT_API_KEY`` / ``DEEPSEEK_API_KEY`` env
2. Dashboard Agent settings in ``~/.loom/state.db`` (BYOK)

Prints the model response to stdout for the worker to capture.
"""

from __future__ import annotations

import argparse
import os
import sys

from daemon.llm_client import LlmClient, LlmError, DEFAULT_MODEL, DEFAULT_BASE_URL


def _settings_db_path() -> str:
    return os.path.expanduser(os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))


def load_llm_config_from_settings(db_path: str | None = None) -> tuple[str, str, str]:
    """Return ``(api_key, base_url, model)`` from agent_settings, or empty key."""
    from daemon.agent_credentials import load_stored_credentials
    creds = load_stored_credentials(db_path or _settings_db_path())
    return creds.llm_from_stored()


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
