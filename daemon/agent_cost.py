"""Cost and quality summary helpers for Loom Agent suggestions."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

JEV_USD_PER_MTOK = 0.042


def jev_cost_usd(input_tokens: int, price_per_mtok: float = JEV_USD_PER_MTOK) -> float:
    return (max(int(input_tokens or 0), 0) / 1_000_000) * float(price_per_mtok)


def llm_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_mtok: float | None,
    output_price_per_mtok: float | None,
) -> float | None:
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


def summarize_suggestions(rows: Iterable[Any]) -> dict[str, Any]:
    """Aggregate usage and accept/dismiss/escalation rates from suggestion rows."""
    rows = list(rows)
    n = len(rows)
    jev_in = prompt = completion = escalated = accepted = dismissed = pending = 0
    for row in rows:
        jev_in += int(_row_get(row, "jev_input_tokens") or 0)
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
    resolved = accepted + dismissed
    return {
        "suggestion_count": n,
        "jev_input_tokens": jev_in,
        "llm_prompt_tokens": prompt,
        "llm_completion_tokens": completion,
        "llm_total_tokens": prompt + completion,
        "jev_cost_usd": round(jev_cost_usd(jev_in), 8),
        "escalated_count": escalated,
        "accepted": accepted,
        "dismissed": dismissed,
        "pending": pending,
        "escalation_rate": (escalated / n) if n else 0.0,
        "accept_rate": (accepted / n) if n else 0.0,
        "dismiss_rate": (dismissed / n) if n else 0.0,
        "accept_rate_resolved": (accepted / resolved) if resolved else 0.0,
        "dismiss_rate_resolved": (dismissed / resolved) if resolved else 0.0,
    }


def format_report(
    summary: Mapping[str, Any],
    *,
    deepseek_input_price: float | None = None,
    deepseek_output_price: float | None = None,
) -> str:
    lines = [
        f"suggestions:           {summary['suggestion_count']}",
        f"jev_input_tokens:      {summary['jev_input_tokens']}",
        f"jev_cost_usd:          ${summary['jev_cost_usd']:.6f}  (${JEV_USD_PER_MTOK}/Mtok input)",
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
    acc = summary['accept_rate']
    acc_r = summary['accept_rate_resolved']
    dis = summary['dismiss_rate']
    dis_r = summary['dismiss_rate_resolved']
    esc = summary['escalation_rate']
    lines.append(f"escalated:             {summary['escalated_count']}  (rate {esc:.1%})")
    lines.append(f"accepted:              {summary['accepted']}  (rate {acc:.1%} of all, {acc_r:.1%} of resolved)")
    lines.append(f"dismissed:             {summary['dismissed']}  (rate {dis:.1%} of all, {dis_r:.1%} of resolved)")
    lines.append(f"pending:               {summary['pending']}")
    return chr(10).join(lines) + chr(10)
