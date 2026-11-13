"""CLI entry for loom-agent worker runs (stdout mode).

Invoked as: ``python -m daemon.agent_run --prompt "..."``
Reads DEEPSEEK_API_KEY / settings are not available here; uses env keys.
Prints the model response to stdout for the worker to capture.
"""

from __future__ import annotations

import argparse
import os
import sys

from daemon.llm_client import LlmClient, LlmError, DEFAULT_MODEL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loom agent worktree runner")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default=os.environ.get("LOOM_AGENT_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LOOM_AGENT_API_KEY", "")
    base_url = os.environ.get("LOOM_AGENT_BASE_URL", "https://api.deepseek.com")
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
        text = client.chat(messages, model=args.model)
    except LlmError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
