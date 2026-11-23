#!/usr/bin/env python3
"""Report Loom Agent suggestion usage and compare decision providers.

Examples:
  PYTHONPATH=. python scripts/agent_cost_report.py
  PYTHONPATH=. python scripts/agent_cost_report.py --db ~/.loom/state.db --project my-app
  PYTHONPATH=. python scripts/agent_cost_report.py --deepseek-input-price 0.27 --deepseek-output-price 1.10
  PYTHONPATH=. python scripts/agent_cost_report.py --benchmark

``--benchmark`` runs the fixed task set once per configured decision provider
(typesafe, ollama, gliclass). GLiClass stays filter-only. Live calls need API
keys or a local serve; this is not a CI test. For a single live call per
provider, use ``scripts/decision_provider_smoke.py`` (manual only, not CI).
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

_ROLE_COLUMNS = ("filter_provider", "judgment_provider", "threshold_overrides_json")


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
    parser.add_argument("--deepseek-input-price", type=float, default=None, help="Optional DeepSeek input USD per million tokens")
    parser.add_argument("--deepseek-output-price", type=float, default=None, help="Optional DeepSeek output USD per million tokens")
    parser.add_argument("--benchmark", action="store_true", help="Compare configured decision providers on the fixed task set (requires API keys)")
    return parser.parse_args(argv)


def resolve_benchmark_credentials(db_path: str | None = None):
    """Settings first, then env.

    Returns ``(typesafe_key, typesafe_base, llm_key, llm_base, model, api_style)``.
    """
    from daemon.agent_credentials import (
        load_stored_credentials,
        resolve_chat_key,
        resolve_typesafe_base_url,
        resolve_typesafe_key,
    )
    creds = load_stored_credentials(db_path)
    stored_llm_key, llm_base, model, api_style = creds.llm_from_stored()
    llm_key = resolve_chat_key(creds.active_chat_provider_id(), stored_llm_key)
    typesafe_key = resolve_typesafe_key(creds.typesafe_key)
    typesafe_base = resolve_typesafe_base_url(creds.typesafe_base_url)
    return typesafe_key, typesafe_base, llm_key, llm_base, model, api_style


def _keys_present(db_path: str | None = None) -> bool:
    typesafe_key, _, llm_key, _, _, _ = resolve_benchmark_credentials(db_path)
    return bool(typesafe_key) and bool(llm_key)


def _db_path(db_path: str | None) -> str:
    return os.path.expanduser(db_path or os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))


def _first_model(model_ids: list | None, default: str = "") -> str:
    for model_id in model_ids or []:
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip()
    return default


def _provider_row(providers: list[dict], provider_id: str) -> dict:
    for row in providers:
        if (row.get("id") or "") == provider_id:
            return row
    return {}


def load_role_settings(db_path: str | None = None) -> dict:
    """Read decision role columns when the settings table has them."""
    path = _db_path(db_path)
    empty = {"filter_provider": None, "judgment_provider": None, "threshold_overrides": None}
    if not os.path.exists(path):
        return empty
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_settings)").fetchall()}
        wanted = [name for name in _ROLE_COLUMNS if name in cols]
        if not wanted or "agent_settings" not in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            conn.close()
            return empty
        selected = conn.execute(
            "SELECT " + ", ".join(wanted) + " FROM agent_settings WHERE id = 1"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return empty
    if selected is None:
        return empty
    data = dict(selected)
    overrides = data.get("threshold_overrides_json")
    return {
        "filter_provider": data.get("filter_provider"),
        "judgment_provider": data.get("judgment_provider"),
        "threshold_overrides": overrides,
    }


def _endpoint(provider: str, model: str, base_url: str, api_key: str) -> dict:
    return {"provider": provider, "model": model, "base_url": base_url or "", "api_key": api_key or ""}


def _target(name: str, filter_end: dict, judgment_end: dict) -> dict:
    providers: list[dict] = []
    keys: dict[str, str] = {}

    def add(endpoint: dict) -> None:
        provider = endpoint["provider"]
        if not provider or provider == "none" or any(row.get("id") == provider for row in providers):
            return
        model = endpoint.get("model") or ""
        providers.append({
            "id": provider,
            "name": provider,
            "base_url": endpoint.get("base_url") or "",
            "model_ids": [model] if model else [],
        })
        if endpoint.get("api_key"):
            keys[provider] = endpoint["api_key"]

    add(filter_end)
    add(judgment_end)
    return {
        "name": name,
        "filter_provider": filter_end["provider"],
        "filter_model": filter_end.get("model") or "",
        "judgment_provider": judgment_end["provider"],
        "judgment_model": judgment_end.get("model") or "",
        "settings": {
            "filter_provider": filter_end["provider"],
            "judgment_provider": judgment_end["provider"],
            "providers": providers,
            "threshold_overrides": None,
        },
        "raw_keys": keys,
    }


def _judgment_for_gliclass(explicit: str | None, runnable: dict[str, dict]) -> dict:
    preferred = (explicit or "").strip().lower()
    if preferred == "none":
        return _endpoint("none", "", "", "")
    if preferred in runnable and preferred != "gliclass":
        return runnable[preferred]
    if "typesafe" in runnable:
        return runnable["typesafe"]
    if "ollama" in runnable:
        return runnable["ollama"]
    return _endpoint("none", "", "", "")


def configured_decision_targets(db_path: str | None = None) -> list[dict]:
    """Decision providers that have enough config for one live call.

    typesafe needs an API key. ollama needs a model. gliclass needs a base URL
    and is filter-only (judgment stays on a configured Jev/Ollama backend, or none).
    """
    from daemon.agent_credentials import (
        DEFAULT_OLLAMA_BASE_URL,
        load_stored_credentials,
        resolve_typesafe_base_url,
        resolve_typesafe_key,
    )
    from daemon.jev_client import DEFAULT_MODEL as DEFAULT_TYPESAFE_MODEL

    creds = load_stored_credentials(db_path)
    roles = load_role_settings(db_path)
    providers = list(creds.providers)
    runnable: dict[str, dict] = {}

    typesafe_key = resolve_typesafe_key(creds.typesafe_key)
    if typesafe_key:
        row = _provider_row(providers, "typesafe")
        model = _first_model(row.get("model_ids"), DEFAULT_TYPESAFE_MODEL)
        base = resolve_typesafe_base_url(row.get("base_url")) or ""
        runnable["typesafe"] = _endpoint("typesafe", model, base, typesafe_key)

    ollama_row = _provider_row(providers, "ollama")
    ollama_model = _first_model(ollama_row.get("model_ids"), os.environ.get("OLLAMA_MODEL", ""))
    if ollama_model:
        base = (ollama_row.get("base_url") or "").strip() or os.environ.get("OLLAMA_BASE_URL", "") or DEFAULT_OLLAMA_BASE_URL
        ollama_key = creds.keys.get("ollama") or os.environ.get("OLLAMA_API_KEY", "")
        runnable["ollama"] = _endpoint("ollama", ollama_model, base, ollama_key)

    targets = [_target(name, endpoint, endpoint) for name, endpoint in runnable.items()]
    overrides = roles.get("threshold_overrides")
    for target in targets:
        target["settings"]["threshold_overrides"] = overrides

    gliclass_row = _provider_row(providers, "gliclass")
    gliclass_base = (gliclass_row.get("base_url") or "").strip() or os.environ.get("GLICLASS_BASE_URL", "")
    if gliclass_base:
        model = _first_model(gliclass_row.get("model_ids"), "")
        filt = _endpoint("gliclass", model, gliclass_base, creds.keys.get("gliclass") or "")
        judgment = _judgment_for_gliclass(roles.get("judgment_provider"), runnable)
        gliclass = _target("gliclass", filt, judgment)
        gliclass["settings"]["threshold_overrides"] = overrides
        targets.append(gliclass)
    return targets


def _result_row(result) -> dict:
    return {
        "filter_provider": result.filter_provider,
        "filter_model": result.filter_model,
        "judgment_provider": result.judgment_provider,
        "judgment_model": result.judgment_model,
        "filter_input_tokens": result.filter_input_tokens,
        "judgment_input_tokens": result.judgment_input_tokens,
        "filter_skipped": result.filter_skipped,
        "judgment_skipped": result.judgment_skipped,
        "filter_skip_reason": result.filter_skip_reason,
        "judgment_skip_reason": result.judgment_skip_reason,
        "filter_latency_ms": result.filter_latency_ms,
        "judgment_latency_ms": result.judgment_latency_ms,
        "llm_prompt_tokens": result.llm_prompt_tokens,
        "llm_completion_tokens": result.llm_completion_tokens,
        "escalated": result.escalated,
        "status": "pending",
        "action_id": result.action_id,
        "jev_input_tokens": result.jev_input_tokens,
    }


def _failed_row(variant: dict, reason: str) -> dict:
    return {
        "filter_provider": variant.get("filter_provider") or "",
        "filter_model": variant.get("filter_model") or "",
        "judgment_provider": variant.get("judgment_provider") or "",
        "judgment_model": variant.get("judgment_model") or "",
        "filter_input_tokens": None,
        "judgment_input_tokens": None,
        "filter_skipped": True,
        "judgment_skipped": True,
        "filter_skip_reason": reason,
        "judgment_skip_reason": reason,
        "filter_latency_ms": None,
        "judgment_latency_ms": None,
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "escalated": True,
        "status": "pending",
        "action_id": "",
        "jev_input_tokens": 0,
    }


async def _run_benchmark_cycle(variant: dict, db_path: str | None = None) -> list[dict]:
    from daemon.decision import clear_decision_client_cache
    from daemon.models import AgentTaskRecord, AgentTaskStatus
    from daemon.orchestrator import Orchestrator, clear_filter_cache

    _, _, llm_key, llm_base, model, api_style = resolve_benchmark_credentials(db_path)
    clear_filter_cache()
    clear_decision_client_cache()

    class _GE:
        def __init__(self, hits):
            self.hits = hits

        async def hybrid_query(self, *a, **k):
            return list(self.hits)

    rows = []
    tmp = Path("/tmp/loom-agent-benchmark")
    (tmp / "graphify-out").mkdir(parents=True, exist_ok=True)
    (tmp / "graphify-out" / "graph.json").write_text("{}")
    from daemon.llm_client import build_llm_client
    llm = build_llm_client(api_key=llm_key, base_url=llm_base, api_style=api_style)
    for i, spec in enumerate(FIXED_BENCHMARK_TASKS):
        status = AgentTaskStatus(spec["status"])
        task = AgentTaskRecord(
            id=f"bench-{variant.get('name', 'run')}-{i}", project="benchmark", title=spec["title"],
            instruction=spec["instruction"], status=status,
            created_at="now", updated_at="now",
        )
        orch = Orchestrator(_GE(spec["hits"]), llm=llm)
        try:
            result = await orch.run_suggest_cycle(
                str(tmp), "benchmark", task,
                prefetched_hits=spec["hits"],
                always_llm=bool(variant.get("always_llm")),
                model=model,
                settings=variant.get("settings"),
                raw_keys=variant.get("raw_keys"),
            )
            rows.append(_result_row(result))
        except Exception as exc:
            print(f"benchmark task {task.id} failed: {type(exc).__name__}", file=sys.stderr)
            rows.append(_failed_row(variant, "error"))
    clear_decision_client_cache()
    return rows


def _baseline_variant(targets: list[dict], roles: dict) -> dict:
    by_provider = {item["filter_provider"]: item for item in targets}
    preferred = (roles.get("filter_provider") or "").strip().lower()
    chosen = by_provider.get(preferred) or by_provider.get("typesafe") or targets[0]
    variant = dict(chosen)
    variant["name"] = "baseline"
    variant["always_llm"] = True
    return variant


def _variant_label(variant: dict) -> str:
    filt = variant.get("filter_provider") or "-"
    fmodel = variant.get("filter_model") or "-"
    judg = variant.get("judgment_provider") or "-"
    jmodel = variant.get("judgment_model") or "-"
    return f"{filt}/{fmodel} judgment {judg}/{jmodel}"


def _cost_cell(summary: dict) -> str:
    priced = f"${summary['jev_cost_usd']:.6f}"
    unpriced = bool(summary.get("gliclass_calls")) or any(
        item.get("provider") == "ollama" and int(item.get("input_tokens") or 0) > 0
        for item in (summary.get("providers") or [])
    )
    if unpriced:
        if summary.get("jev_input_tokens"):
            return priced + "+n/a"
        return "n/a"
    return priced


def _latency_cell(summary: dict) -> str:
    """Mean of measured role latencies. Provider ``none`` is already omitted from those averages."""
    values = []
    for role, key in (("filter", "filter_latency_ms_avg"), ("judgment", "judgment_latency_ms_avg")):
        if _role_latency_is_null_only(summary, role):
            continue
        value = summary.get(key)
        if value is not None:
            values.append(value)
    if not values:
        return "n/a"
    return f"{sum(values) / len(values):.1f}"


def _role_latency_is_null_only(summary: dict, role: str) -> bool:
    rows = [item for item in (summary.get("providers") or []) if item.get("role") == role and item.get("latency_ms_avg") is not None]
    if not rows:
        return False
    return all(item.get("provider") == "none" or _null_skip_only(item) for item in rows)


def _null_skip_only(item: dict) -> bool:
    reasons = item.get("skips_by_reason") or {}
    return "none" in reasons and not item.get("input_tokens") and set(reasons) <= {"none"}


def format_comparison(items: list[tuple[str, dict]]) -> str:
    header = f"{'run':<44} {'tokens':>8} {'cost':>16} {'filt_skip':>10} {'judg_skip':>10} {'escalate':>10} {'accept':>8} {'dismiss':>8} {'lat_ms':>8}"
    lines = [header]
    for label, summary in items:
        tokens = int(summary.get("filter_input_tokens") or 0) + int(summary.get("judgment_input_tokens") or 0) + int(summary.get("legacy_input_tokens") or 0)
        lines.append(
            f"{label[:44]:<44} {tokens:>8} {_cost_cell(summary):>16} "
            f"{summary.get('filter_skip_rate', 0):>10.1%} {summary.get('judgment_skip_rate', 0):>10.1%} "
            f"{summary.get('escalation_rate', 0):>10.1%} {summary.get('accept_rate', 0):>8.1%} "
            f"{summary.get('dismiss_rate', 0):>8.1%} {_latency_cell(summary):>8}"
        )
    lines.append("accept/dismiss stay 0 here: the benchmark does not persist suggestion outcomes.")
    lines.append(
        f"priced decision tokens (typesafe only) use ${JEV_USD_PER_MTOK}/Mtok. "
        "Ollama and GLiClass decision-token $ is n/a."
    )
    return "\n".join(lines) + "\n"


def run_benchmark(db_path: str | None = None) -> int:
    _, _, llm_key, _, _, _ = resolve_benchmark_credentials(db_path)
    targets = configured_decision_targets(db_path)
    if not llm_key or not targets:
        print(
            "Skipping benchmark: a chat LLM API key and a configured decision provider "
            "(TYPESAFE_API_KEY, an Ollama model, or a GLiClass URL) are required "
            "(dashboard Agent settings and env).",
            file=sys.stderr,
        )
        return 0
    roles = load_role_settings(db_path)
    print("Running benchmark: fixed tasks across configured decision providers...")
    print("accept/dismiss: pending only (outcomes are not persisted in this run).")
    runs: list[tuple[str, dict]] = [("baseline (always-DeepSeek)", _baseline_variant(targets, roles))]
    for target in targets:
        variant = dict(target)
        variant["always_llm"] = False
        runs.append((_variant_label(variant), variant))
    summaries: list[tuple[str, dict]] = []
    for label, variant in runs:
        print(f"\n== {label} ==")
        rows = asyncio.run(_run_benchmark_cycle(variant, db_path=db_path))
        summary = summarize_suggestions(rows)
        summaries.append((label, summary))
        print(format_report(
            summary,
            deepseek_input_price=None,
            deepseek_output_price=None,
        ))
    print("== comparison ==")
    print(format_comparison(summaries))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.benchmark:
        return run_benchmark(args.db)
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
