"use client";

import { useTranslations, useFormatter } from "next-intl";

interface DispatchInfo {
  task_id: string;
  target_agent: string;
  instruction: string;
  status: string;
  dispatched_at: string;
  priority?: string;
}

interface DispatchHistoryProps {
  dispatches: DispatchInfo[];
}

export function DispatchHistory({ dispatches }: DispatchHistoryProps) {
  const t = useTranslations("DispatchHistory");
  const tStatus = useTranslations("Common.status");
  const format = useFormatter();

  const statusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-emerald-900/50 text-emerald-300 border-emerald-700";
      case "pending":
        return "bg-amber-900/50 text-amber-300 border-amber-700";
      case "failed":
        return "bg-red-900/50 text-red-300 border-red-700";
      default:
        return "bg-zinc-800 text-zinc-400 border-zinc-700";
    }
  };

  if (dispatches.length === 0) {
    return (
      <div className="text-sm text-zinc-600 text-center py-6">{t("empty")}</div>
    );
  }

  return (
    <div className="border border-zinc-800 rounded-lg overflow-hidden">
      <div className="grid grid-cols-[1fr_100px_80px_140px] gap-2 px-4 py-2 bg-zinc-900 text-[11px] text-zinc-500 font-semibold uppercase border-b border-zinc-800">
        <span>{t("colInstruction")}</span>
        <span>{t("colTarget")}</span>
        <span>{t("colStatus")}</span>
        <span className="text-end">{t("colDispatched")}</span>
      </div>
      {dispatches.map((d) => (
        <div
          key={d.task_id}
          className="grid grid-cols-[1fr_100px_80px_140px] gap-2 px-4 py-2.5 border-b border-zinc-800/50 text-sm hover:bg-zinc-900/50"
        >
          <span className="text-zinc-300 truncate">{d.instruction}</span>
          <span className="text-zinc-400 text-xs font-mono">{d.target_agent}</span>
          <span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${statusBadge(d.status)}`}>
              {tStatus(d.status as never)}
            </span>
          </span>
          <span className="text-zinc-600 text-xs text-end">
            {format.dateTime(new Date(d.dispatched_at), {
              dateStyle: "short",
              timeStyle: "short",
            })}
          </span>
        </div>
      ))}
    </div>
  );
}
