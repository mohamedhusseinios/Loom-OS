#!/usr/bin/env python3
"""Report Loom Agent suggestion usage and optionally benchmark two paths.

Examples:
  PYTHONPATH=. python scripts/agent_cost_report.py
  PYTHONPATH=. python scripts/agent_cost_report.py --db ~/.loom/state.db --project my-app
  PYTHONPATH=. python scripts/agent_cost_report.py --deepseek-input-price 0.27 --deepseek-output-price 1.10
  PYTHONPATH=. python scripts/agent_cost_report.py --benchmark
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

# Allow running from repo root or scripts/.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daemon.agent_cost import (  # noqa: E402
    JEV_USD_PER_MTOK,
    format_report,
    summarize_suggestions,
)

DEFAULT_DB = os.path.expanduser(os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))

FIXED_BENCHMARK_TASKS = [
    {
        "title": "Extract card validation",
        "instruction": "Move checkout card validation into a shared helper used by web and mobile.",
        "status": "todo",
        "hits": [
            {"id": "checkout.CardForm", "label": "CardForm"},
            {"id": "payments.validate", "label": "validate_card"},
            {"id": "ui.Banner", "label": "unused banner"},
        ],
    },
    {
        "title": "Fix null on empty cart",
        "instruction": "The cart total crashes when the cart is empty. Guard the calculation.",
        "status": "ready",
        "hits": [
            {"id": "cart.Totals", "label": "CartTotals"},
            {"id": "cart.EmptyState", "label": "EmptyState"},
        ],
    },
    {
        "title": "Unblock review comments",
        "instruction": "Address review comments on the auth middleware PR.",
        "status": "blocked",
        "hits": [
            {"id": "auth.Middleware", "label": "AuthMiddleware"},
            {"id": "auth.Tokens", "label": "TokenStore"},
        ],
    },
]


def load_suggestions(db_path: str, project: str | None = None) -> list[dict]:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_suggestions)").fetchall()}
    if not cols:
        conn.close()
        return []
    sql = "SELECT * FROM task_suggestions"
    params: list[str] = []
    if project:
        sql += " WHERE project = ?"
        params.append(project)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Loom Agent suggestion cost report")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to state.db (default: LOOM_DB_PATH or ~/.loom/state.db)")
    parser.add_argument("--project", default=None, help="Limit to one project id")
    parser.add_argument(
        "--deepseek-input-price",
        type=float,
        default=None,
        help="Optional DeepSeek input USD per million tokens",
    )
    parser.add_argument(
        "--deepseek-output-price",
        type=float,
        default=None,
        help="Optional DeepSeek output USD per million tokens",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run fixed tasks through always-DeepSeek vs the new path (requires API keys)",
    )
    return parser.parse_args(argv)


def _keys_present() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY")) and bool(
        os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LOOM_AGENT_API_KEY")
    )


async def _run_benchmark_cycle(always_llm: bool) -> list[dict]:
    from daemon.jev_client import JevClient
    from daemon.llm_client import LlmClient
    from daemon.models import AgentTaskRecord, AgentTaskStatus
    from daemon.orchestrator import Orchestrator, clear_filter_cache

    class _GE:
        def __init__(self, hits):
            self.hits = hits

        async def hybrid_query(self, *a, **k):
            return list(self.hits)

    clear_filter_cache()
    rows = []
    tmp = Path("/tmp/loom-agent-benchmark")
    (tmp / "graphify-out").mkdir(parents=True, exist_ok=True)
    (tmp / "graphify-out" / "graph.json").write_text("{}")
    for i, spec in enumerate(FIXED_BENCHMARK_TASKS):
        status = AgentTaskStatus(spec["status"])
        task = AgentTaskRecord(
            id=f"bench-{i}", project="benchmark", title=spec["title"],
            instruction=spec["instruction"], status=status,
            created_at="now", updated_at="now",
        )
        orch = Orchestrator(
            _GE(spec["hits"]),
            jev=JevClient(),
            llm=LlmClient(),
        )
        result = await orch.run_suggest_cycle(
            str(tmp), "benchmark", task,
            prefetched_hits=spec["hits"],
            always_llm=always_llm,
        )
        rows.append({
            "jev_input_tokens": result.jev_input_tokens,
            "llm_prompt_tokens": result.llm_prompt_tokens,
            "llm_completion_tokens": result.llm_completion_tokens,
            "escalated": result.escalated,
            "status": "pending",
            "action_id": result.action_id,
        })
    return rows


def run_benchmark() -> int:
    if not _keys_present():
        print(
            "Skipping benchmark: TYPESAFE_API_KEY and/or DEEPSEEK_API_KEY is not set.",
            file=sys.stderr,
        )
        return 0
    print("Running benchmark: baseline (always-DeepSeek) vs new path...")
    baseline = asyncio.run(_run_benchmark_cycle(always_llm=True))
    current = asyncio.run(_run_benchmark_cycle(always_llm=False))
    print("\n== baseline (always-DeepSeek) ==")
    print(format_report(summarize_suggestions(baseline)))
    print("== new path ==")
    print(format_report(summarize_suggestions(current)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.benchmark:
        return run_benchmark()
    try:
        rows = load_suggestions(args.db, args.project)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    summary = summarize_suggestions(rows)
    print(f"database:  {args.db}")
    if args.project:
        print(f"project:   {args.project}")
    print(format_report(
        summary,
        deepseek_input_price=args.deepseek_input_price,
        deepseek_output_price=args.deepseek_output_price,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
