#!/usr/bin/env python3
"""Manual live smoke for decision providers. Not CI.

One live ``filter_relevance`` call per configured provider:

- typesafe — needs a TypeSafe API key (dashboard settings, else ``TYPESAFE_API_KEY``)
- ollama — needs a model id (provider ``model_ids`` or ``OLLAMA_MODEL``)
- gliclass — needs a base URL (provider ``base_url`` or ``GLICLASS_BASE_URL``); filter only

Do not wire this script into pytest or GitHub Actions. It talks to real services.

Usage:
  PYTHONPATH=. python scripts/decision_provider_smoke.py
  PYTHONPATH=. python scripts/decision_provider_smoke.py --db ~/.loom/state.db
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_cost_report import configured_decision_targets  # noqa: E402

MANUAL_BANNER = "Manual only — not CI. One live call per configured decision provider (typesafe, ollama, gliclass)."
_FAILURE_REASONS = frozenset({"error", "timeout", "bad_payload"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual decision-provider smoke (not CI)")
    parser.add_argument("--db", default=None, help="Path to state.db (default: LOOM_DB_PATH or ~/.loom/state.db)")
    return parser.parse_args(argv)


def call_provider(target: dict):
    """One live filter call. Returns the DecisionResult. Not for CI."""
    from daemon.decision import build_decision_clients, clear_decision_client_cache, resolve_decision_config

    config = resolve_decision_config(target["settings"], target.get("raw_keys"))
    relevance, _judgment = build_decision_clients(config)
    task = {
        "title": "Decision provider smoke",
        "instruction": "Score whether the node is relevant to this ping.",
        "status": "todo",
    }
    hits = [{"id": "smoke.Node", "label": "smoke node"}]
    try:
        return relevance.filter_relevance(pack="smoke node", task=task, catalog=[], hits=hits)
    finally:
        clear_decision_client_cache()


def _line(target: dict, result) -> str:
    reason = result.skip_reason or "-"
    tokens = result.usage.input_tokens
    token_text = "n/a" if tokens is None else str(tokens)
    return (
        f"{target['filter_provider']}/{target.get('filter_model') or '-'} "
        f"skipped={result.skipped} reason={reason} latency_ms={result.latency_ms:.1f} input_tokens={token_text}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(MANUAL_BANNER)
    targets = [item for item in configured_decision_targets(args.db) if item["filter_provider"] in {"typesafe", "ollama", "gliclass"}]
    if not targets:
        print("No configured decision provider. Set a TypeSafe key, an Ollama model, or a GLiClass base URL.")
        return 0
    failed = False
    for target in targets:
        try:
            result = call_provider(target)
        except Exception as exc:
            print(f"{target['filter_provider']}: call failed ({type(exc).__name__})")
            failed = True
            continue
        print(_line(target, result))
        if result.skipped and (result.skip_reason in _FAILURE_REASONS or result.skip_reason is None):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
