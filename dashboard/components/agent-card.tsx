"use client";

import { useState } from "react";
import { useTranslations, useFormatter } from "next-intl";
import { ChevronDown, ChevronUp } from "lucide-react";
import { timeAgo } from "@/lib/time-ago";

interface AgentCardProps {
  agent: {
    agent_id: string;
    agent_name: string;
    version: string;
    status: "online" | "offline" | "working";
    capabilities: string[];
    last_heartbeat: string | null;
    registered_at: string;
    finding_count?: number;
  };
}

export function AgentCard({ agent }: AgentCardProps) {
  const t = useTranslations("AgentCard");
  const tStatus = useTranslations("Common.status");
  const tTime = useTranslations("Common.timeAgo");
  const format = useFormatter();
  const [expanded, setExpanded] = useState(false);

  const initials = agent.agent_name
    .split("-")
    .map((w) => w[0]?.toUpperCase())
    .join("")
    .slice(0, 2);

  const statusBorder = {
    online: "border-emerald-700 bg-emerald-900/20",
    working: "border-amber-700 bg-amber-900/20",
    offline: "border-zinc-700 bg-zinc-800/20",
  };

  const dotColor = {
    online: "bg-emerald-400",
    working: "bg-amber-400",
    offline: "bg-zinc-600",
  };

  const avatarBg = {
    online: "bg-emerald-900 text-emerald-300",
    working: "bg-amber-900 text-amber-300",
    offline: "bg-zinc-800 text-zinc-500",
  };

  const registered = timeAgo(agent.last_heartbeat, tTime);

  return (
    <div
      className={`border rounded-xl p-4 cursor-pointer transition-colors ${statusBorder[agent.status]}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-3">
        <div
          className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold text-sm ${avatarBg[agent.status]}`}
        >
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="font-semibold text-sm text-zinc-100">{agent.agent_name}</h4>
            <div className={`w-2 h-2 rounded-full ${dotColor[agent.status]}`} />
          </div>
          <p className="text-[11px] text-zinc-500">
            {agent.version} · {t("registeredAt", { timeAgo: registered })}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-zinc-400">
          <span>{t("capabilities", { count: agent.capabilities.length })}</span>
          {agent.finding_count !== undefined && (
            <span>{t("findings", { count: agent.finding_count })}</span>
          )}
          <span className="text-[10px] uppercase text-zinc-600">{tStatus(agent.status)}</span>
          {expanded ? (
            <ChevronUp className="w-3.5 h-3.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 rtl:-scale-x-100" />
          )}
        </div>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-zinc-700/50">
          <div className="flex flex-wrap gap-1.5 mb-2">
            {agent.capabilities.map((c) => (
              <span key={c} className="text-[10px] bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded-full">
                {c}
              </span>
            ))}
          </div>
          <div className="text-[10px] text-zinc-600">
            {t("lastHeartbeat", {
              time: agent.last_heartbeat
                ? format.dateTime(new Date(agent.last_heartbeat), {
                    dateStyle: "short",
                    timeStyle: "short",
                  })
                : tTime("never"),
            })}
          </div>
        </div>
      )}
    </div>
  );
}
