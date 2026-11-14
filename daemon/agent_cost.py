"""Cost and quality summary helpers for Loom Agent suggestions.

Decision tokens come from ``filter_input_tokens`` and ``judgment_input_tokens``.
GLiClass has no token price (reported as n/a). Rows written before those columns
exist fall back to ``legacy_decision_input_tokens``, then ``jev_input_tokens``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

JEV_USD_PER_MTOK = 0.042
_SKIP_REASON_ORDER = ("none", "error", "timeout", "bad_payload", "unsupported", "unspecified", "legacy")
_ROLES = ("filter", "judgment")


def jev_cost_usd(input_tokens: int, price_per_mtok: float = JEV_USD_PER_MTOK) -> float:
    return (max(int(input_tokens or 0), 0) / 1_000_000) * float(price_per_mtok)


def llm_cost_usd(prompt_tokens: int, completion_tokens: int, input_price_per_mtok: float | None, output_price_per_mtok: float | None) -> float | None:
    if input_price_per_mtok is None and output_price_per_mtok is None:
        return None
    inp = (max(int(prompt_tokens or 0), 0) / 1_000_000) * float(input_price_per_mtok or 0)
    out = (max(int(completion_tokens or 0), 0) / 1_000_000) * float(output_price_per_mtok or 0)
    return inp + out


def _row_get(row: Mapping[str, Any] | Any, *names: str, default: Any = 0) -> Any:
    for name in names:
        if isinstance(row, Mapping) and name in row:
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
        try:
            return row[name]
        except Exception:
            continue
    return default


def _row_has(row: Mapping[str, Any] | Any, name: str) -> bool:
    if isinstance(row, Mapping):
        return name in row
    return hasattr(row, name)


def _opt_int(row: Mapping[str, Any] | Any, name: str) -> int | None:
    if not _row_has(row, name):
        return None
    value = _row_get(row, name, default=None)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_float(row: Mapping[str, Any] | Any, name: str) -> float | None:
    if not _row_has(row, name):
        return None
    value = _row_get(row, name, default=None)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_text(row: Mapping[str, Any] | Any, name: str) -> str | None:
    if not _row_has(row, name):
        return None
    value = _row_get(row, name, default=None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_bool(row: Mapping[str, Any] | Any, name: str) -> bool | None:
    if not _row_has(row, name):
        return None
    value = _row_get(row, name, default=None)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _reason_key(reason: str | None) -> str:
    text = (reason or "unspecified").strip().lower() or "unspecified"
    return text


def _sorted_reasons(counts: Mapping[str, int]) -> dict[str, int]:
    ordered = [name for name in _SKIP_REASON_ORDER if counts.get(name)]
    ordered.extend(sorted(name for name in counts if name not in _SKIP_REASON_ORDER and counts[name]))
    return {name: int(counts[name]) for name in ordered}


def _empty_bucket(role: str, provider: str, model: str) -> dict[str, Any]:
    return {
        "role": role,
        "provider": provider,
        "model": model,
        "calls": 0,
        "input_tokens": 0,
        "priced": provider != "gliclass" and provider != "none",
        "skipped": 0,
        "reasons": {},
        "latency_sum": 0.0,
        "latency_n": 0,
    }


def _rates(counts: Mapping[str, int], denominator: int) -> dict[str, float]:
    if not denominator:
        return {}
    return {name: count / denominator for name, count in counts.items()}


def _avg(total: float, count: int) -> float | None:
    if not count:
        return None
    return total / count


def summarize_suggestions(rows: Iterable[Any]) -> dict[str, Any]:
    """Aggregate usage, provider cost, skip reasons, latency, and outcomes."""
    rows = list(rows)
    n = len(rows)
    prompt = completion = escalated = accepted = dismissed = pending = 0
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    filter_reasons: dict[str, int] = {}
    judgment_reasons: dict[str, int] = {}
    filter_skipped_count = judgment_skipped_count = 0
    filter_latency_sum = judgment_latency_sum = 0.0
    filter_latency_n = judgment_latency_n = 0

    def bucket_for(role: str, provider: str, model: str) -> dict[str, Any]:
        key = (role, provider, model)
        found = buckets.get(key)
        if found is None:
            found = _empty_bucket(role, provider, model)
            buckets[key] = found
        return found

    def note_skip(role: str, reason: str | None) -> None:
        nonlocal filter_skipped_count, judgment_skipped_count
        key = _reason_key(reason)
        if role == "filter":
            filter_skipped_count += 1
            filter_reasons[key] = filter_reasons.get(key, 0) + 1
        elif role == "judgment":
            judgment_skipped_count += 1
            judgment_reasons[key] = judgment_reasons.get(key, 0) + 1

    for row in rows:
        prompt += int(_row_get(row, "llm_prompt_tokens") or 0)
        completion += int(_row_get(row, "llm_completion_tokens") or 0)
        if _row_get(row, "escalated", default=False):
            escalated += 1
        raw_status = _row_get(row, "status", default="")
        status = str(getattr(raw_status, "value", raw_status) or "")
        if status == "accepted":
            accepted += 1
        elif status == "dismissed":
            dismissed += 1
        elif status == "pending":
            pending += 1

        saw_role = False
        for role in _ROLES:
            provider = (_opt_text(row, f"{role}_provider") or "").lower()
            model = _opt_text(row, f"{role}_model") or ""
            tokens = _opt_int(row, f"{role}_input_tokens")
            skipped = _opt_bool(row, f"{role}_skipped")
            reason = _opt_text(row, f"{role}_skip_reason")
            latency = _opt_float(row, f"{role}_latency_ms")
            if skipped is None:
                skipped = bool(reason)
            if not provider and tokens is None and latency is None and not skipped:
                continue
            saw_role = True
            provider_name = provider or "unknown"
            item = bucket_for(role, provider_name, model)
            item["calls"] += 1
            if tokens is not None:
                item["input_tokens"] += tokens
            if latency is not None:
                item["latency_sum"] += latency
                item["latency_n"] += 1
                if role == "filter":
                    filter_latency_sum += latency
                    filter_latency_n += 1
                else:
                    judgment_latency_sum += latency
                    judgment_latency_n += 1
            if skipped:
                item["skipped"] += 1
                reason_key = _reason_key(reason)
                item["reasons"][reason_key] = item["reasons"].get(reason_key, 0) + 1
                note_skip(role, reason_key)

        if saw_role:
            continue
        legacy_tokens = _opt_int(row, "legacy_decision_input_tokens")
        if legacy_tokens is None:
            legacy_tokens = _opt_int(row, "jev_input_tokens")
        legacy_skipped = bool(_row_get(row, "jev_skipped", default=False))
        if not legacy_tokens and not legacy_skipped:
            continue
        provider_name = (_opt_text(row, "filter_provider") or "typesafe").lower()
        model = _opt_text(row, "filter_model") or ""
        item = bucket_for("legacy", provider_name, model)
        item["calls"] += 1
        if legacy_tokens:
            item["input_tokens"] += legacy_tokens
        if legacy_skipped:
            item["skipped"] += 1
            item["reasons"]["legacy"] = item["reasons"].get("legacy", 0) + 1

    providers: list[dict[str, Any]] = []
    filter_tokens = judgment_tokens = legacy_tokens_total = gliclass_tokens = priced_tokens = 0
    gliclass_calls = 0
    for item in buckets.values():
        tokens = int(item["input_tokens"])
        if item["role"] == "filter":
            filter_tokens += tokens
        elif item["role"] == "judgment":
            judgment_tokens += tokens
        else:
            legacy_tokens_total += tokens
        if item["provider"] == "gliclass":
            gliclass_tokens += tokens
            gliclass_calls += int(item["calls"])
            cost: float | None = None
        elif item["priced"]:
            priced_tokens += tokens
            cost = round(jev_cost_usd(tokens), 8)
        else:
            cost = 0.0
        calls = int(item["calls"])
        reasons = _sorted_reasons(item["reasons"])
        providers.append({
            "role": item["role"],
            "provider": item["provider"],
            "model": item["model"],
            "calls": calls,
            "input_tokens": tokens,
            "cost_usd": cost,
            "skipped": int(item["skipped"]),
            "skip_rate": (item["skipped"] / calls) if calls else 0.0,
            "skips_by_reason": reasons,
            "latency_ms_avg": _avg(item["latency_sum"], item["latency_n"]),
        })
    providers.sort(key=lambda item: (item["role"], item["provider"], item["model"]))
    filter_reason_counts = _sorted_reasons(filter_reasons)
    judgment_reason_counts = _sorted_reasons(judgment_reasons)
    resolved = accepted + dismissed
    return {
        "suggestion_count": n,
        "jev_input_tokens": priced_tokens,
        "filter_input_tokens": filter_tokens,
        "judgment_input_tokens": judgment_tokens,
        "legacy_input_tokens": legacy_tokens_total,
        "gliclass_input_tokens": gliclass_tokens,
        "gliclass_calls": gliclass_calls,
        "gliclass_cost_usd": None,
        "llm_prompt_tokens": prompt,
        "llm_completion_tokens": completion,
        "llm_total_tokens": prompt + completion,
        "jev_cost_usd": round(jev_cost_usd(priced_tokens), 8),
        "escalated_count": escalated,
        "accepted": accepted,
        "dismissed": dismissed,
        "pending": pending,
        "escalation_rate": (escalated / n) if n else 0.0,
        "accept_rate": (accepted / n) if n else 0.0,
        "dismiss_rate": (dismissed / n) if n else 0.0,
        "accept_rate_resolved": (accepted / resolved) if resolved else 0.0,
        "dismiss_rate_resolved": (dismissed / resolved) if resolved else 0.0,
        "providers": providers,
        "filter_skipped": filter_skipped_count,
        "judgment_skipped": judgment_skipped_count,
        "filter_skip_rate": (filter_skipped_count / n) if n else 0.0,
        "judgment_skip_rate": (judgment_skipped_count / n) if n else 0.0,
        "filter_skips_by_reason": filter_reason_counts,
        "judgment_skips_by_reason": judgment_reason_counts,
        "filter_skip_rates_by_reason": _rates(filter_reason_counts, n),
        "judgment_skip_rates_by_reason": _rates(judgment_reason_counts, n),
        "filter_latency_ms_avg": _avg(filter_latency_sum, filter_latency_n),
        "judgment_latency_ms_avg": _avg(judgment_latency_sum, judgment_latency_n),
    }


def _fmt_latency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def _fmt_cost(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.6f}"


def _fmt_skips(label: str, counts: Mapping[str, int], rate: float) -> str:
    if not counts:
        body = "none"
    else:
        body = " ".join(f"{name}={counts[name]}" for name in counts)
    return f"{label}: {body}  (rate {rate:.1%})"


def format_report(summary: Mapping[str, Any], *, deepseek_input_price: float | None = None, deepseek_output_price: float | None = None) -> str:
    lines = [
        f"suggestions:           {summary['suggestion_count']}",
        f"jev_input_tokens:      {summary['jev_input_tokens']}",
        f"jev_cost_usd:          ${summary['jev_cost_usd']:.6f}  (${JEV_USD_PER_MTOK}/Mtok input)",
        f"filter_input_tokens:   {summary.get('filter_input_tokens', 0)}",
        f"judgment_input_tokens: {summary.get('judgment_input_tokens', 0)}",
        f"legacy_input_tokens:   {summary.get('legacy_input_tokens', 0)}",
        f"gliclass_input_tokens: {summary.get('gliclass_input_tokens', 0)}",
        "gliclass_cost_usd:     n/a",
        f"llm_prompt_tokens:     {summary['llm_prompt_tokens']}",
        f"llm_completion_tokens: {summary['llm_completion_tokens']}",
        f"llm_total_tokens:      {summary['llm_total_tokens']}",
    ]
    llm_usd = llm_cost_usd(
        int(summary["llm_prompt_tokens"]),
        int(summary["llm_completion_tokens"]),
        deepseek_input_price,
        deepseek_output_price,
    )
    if llm_usd is None:
        lines.append("llm_cost_usd:          n/a (pass --deepseek-input-price / --deepseek-output-price)")
    else:
        lines.append(f"llm_cost_usd:          ${llm_usd:.6f}")
    lines.append("by_provider:")
    providers = list(summary.get("providers") or [])
    if not providers:
        lines.append("  (none)")
    for item in providers:
        model = item.get("model") or "-"
        latency = _fmt_latency(item.get("latency_ms_avg"))
        lines.append(
            f"  {item['role']} {item['provider']}/{model}  calls={item['calls']} tokens={item['input_tokens']} "
            f"cost={_fmt_cost(item.get('cost_usd'))} skip={item['skip_rate']:.1%} latency_ms={latency}"
        )
        reasons = item.get("skips_by_reason") or {}
        if reasons:
            lines.append("    skips: " + " ".join(f"{name}={reasons[name]}" for name in reasons))
    lines.append(_fmt_skips("filter_skips", summary.get("filter_skips_by_reason") or {}, float(summary.get("filter_skip_rate") or 0)))
    lines.append(_fmt_skips("judgment_skips", summary.get("judgment_skips_by_reason") or {}, float(summary.get("judgment_skip_rate") or 0)))
    lines.append(f"filter_latency_ms_avg: {_fmt_latency(summary.get('filter_latency_ms_avg'))}")
    lines.append(f"judgment_latency_ms_avg: {_fmt_latency(summary.get('judgment_latency_ms_avg'))}")
    acc = summary["accept_rate"]
    acc_r = summary["accept_rate_resolved"]
    dis = summary["dismiss_rate"]
    dis_r = summary["dismiss_rate_resolved"]
    esc = summary["escalation_rate"]
    lines.append(f"escalated:             {summary['escalated_count']}  (rate {esc:.1%})")
    lines.append(f"accepted:              {summary['accepted']}  (rate {acc:.1%} of all, {acc_r:.1%} of resolved)")
    lines.append(f"dismissed:             {summary['dismissed']}  (rate {dis:.1%} of all, {dis_r:.1%} of resolved)")
    lines.append(f"pending:               {summary['pending']}")
    return "\n".join(lines) + "\n"
