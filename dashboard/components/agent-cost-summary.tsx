"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getAgentCostSummary, type AgentCostSummary } from "@/lib/api";
import { useWebSocket } from "@/lib/use-websocket";

function pct(rate: number): string {
  return `${Math.round((rate || 0) * 100)}%`;
}

export function AgentCostSummary({ projectId }: { projectId: string }) {
  const t = useTranslations("LoomAgent");
  const { subscribe } = useWebSocket();
  const [summary, setSummary] = useState<AgentCostSummary | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    getAgentCostSummary(projectId)
      .then((data) => {
        setSummary(data);
        setError("");
      })
      .catch(() => setError(t("costLoadError")));
  }, [projectId, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    return subscribe("task:suggestion", (event) => {
      const data = event.data as { project?: string };
      if (!data.project || data.project === projectId) load();
    });
  }, [projectId, subscribe, load]);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 space-y-1">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{t("costSummary")}</p>
      {error && <p className="text-[11px] text-red-400">{error}</p>}
      {!error && !summary && (
        <p className="text-[11px] text-zinc-500">{t("costEmpty")}</p>
      )}
      {summary && summary.suggestion_count === 0 && (
        <p className="text-[11px] text-zinc-500">{t("costEmpty")}</p>
      )}
      {summary && summary.suggestion_count > 0 && (
        <>
          <p className="text-[11px] text-zinc-400">
            {t("costSuggestions", { count: summary.suggestion_count })}
          </p>
          <p className="text-[11px] text-zinc-400">
            {t("costJev", {
              tokens: summary.jev_input_tokens,
              usd: summary.jev_cost_usd.toFixed(4),
            })}
          </p>
          <p className="text-[11px] text-zinc-400">
            {t("costLlm", { tokens: summary.llm_total_tokens })}
          </p>
          <p className="text-[11px] text-zinc-400">
            {t("costEscalation", { rate: pct(summary.escalation_rate) })}
            {" · "}
            {t("costAccept", { rate: pct(summary.accept_rate_resolved) })}
            {" · "}
            {t("costDismiss", { rate: pct(summary.dismiss_rate_resolved) })}
          </p>
        </>
      )}
    </div>
  );
}
