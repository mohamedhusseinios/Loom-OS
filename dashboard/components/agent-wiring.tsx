"use client";

import { useTranslations } from "next-intl";

interface AgentInfo {
  agent_id: string;
  agent_name: string;
  status: string;
  finding_count?: number;
}

interface DispatchInfo {
  task_id: string;
  target_agent: string;
  instruction: string;
  status: string;
}

interface AgentWiringProps {
  agents: AgentInfo[];
  dispatches: DispatchInfo[];
}

export function AgentWiring({ agents, dispatches }: AgentWiringProps) {
  const t = useTranslations("AgentWiring");

  if (agents.length === 0) {
    return (
      <div className="text-sm text-zinc-600 text-center py-8">{t("empty")}</div>
    );
  }

  const initials = (name: string) =>
    name
      .split("-")
      .map((w) => w[0]?.toUpperCase())
      .join("")
      .slice(0, 2);

  const colors = [
    { bg: "bg-emerald-900", border: "border-emerald-700", text: "text-emerald-300", dot: "bg-emerald-400" },
    { bg: "bg-blue-900", border: "border-blue-700", text: "text-blue-300", dot: "bg-blue-400" },
    { bg: "bg-purple-900", border: "border-purple-700", text: "text-purple-300", dot: "bg-purple-400" },
  ];

  return (
    <div className="flex items-center gap-0 justify-center flex-wrap py-4">
      {agents.map((agent, i) => {
        const color = colors[i % colors.length];
        return (
          <div key={agent.agent_id} className="flex items-center gap-0">
            <div className="flex flex-col items-center mx-3">
              <div
                className={`w-14 h-14 rounded-full ${color.bg} border-2 ${color.border} flex items-center justify-center ${color.text} font-bold text-lg`}
              >
                {initials(agent.agent_name)}
              </div>
              <span className="text-[10px] text-zinc-400 mt-1.5">{agent.agent_name}</span>
              <span className="text-[9px] text-zinc-600">
                {t("findings", { count: agent.finding_count || 0 })}
              </span>
              <div className={`w-1.5 h-1.5 rounded-full ${color.dot} mt-0.5`} />
            </div>
            {i < agents.length - 1 && (
              // rtl:scale-x-[-1] mirrors the arrow under RTL.
              <div className="flex items-center text-zinc-700 text-lg mx-1 rtl:-scale-x-100">
                ━━━▶
              </div>
            )}
          </div>
        );
      })}

      {dispatches
        .filter((d) => d.status === "pending")
        .slice(0, 3)
        .map((d) => (
          <div key={d.task_id} className="flex items-center gap-0">
            <div className="flex items-center text-zinc-700 text-lg mx-1 rtl:-scale-x-100">━━━▶</div>
            <div className="flex flex-col items-center mx-3">
              <div className="w-12 h-12 rounded-xl bg-zinc-900 border-2 border-dashed border-zinc-600 flex items-center justify-center text-zinc-500 text-xs">
                📋
              </div>
              <span className="text-[10px] text-zinc-500 mt-1.5">{t("task")}</span>
              <span className="text-[9px] text-zinc-600 truncate max-w-[80px]">{d.target_agent}</span>
              <span className="text-[8px] text-amber-500 mt-0.5">{t("pending")}</span>
            </div>
          </div>
        ))}
    </div>
  );
}
