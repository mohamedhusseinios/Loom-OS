"use client";

import { useTranslations } from "next-intl";

interface GraphStatsProps {
  stats: {
    nodes: number;
    edges: number;
    communities: number;
  };
}

export function GraphStats({ stats }: GraphStatsProps) {
  const t = useTranslations("GraphStats");
  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center">
        <div className="text-2xl font-mono text-emerald-400">{stats.nodes}</div>
        <div className="text-xs text-zinc-500 mt-1">{t("nodes")}</div>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center">
        <div className="text-2xl font-mono text-blue-400">{stats.edges}</div>
        <div className="text-xs text-zinc-500 mt-1">{t("edges")}</div>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center">
        <div className="text-2xl font-mono text-purple-400">{stats.communities}</div>
        <div className="text-xs text-zinc-500 mt-1">{t("communities")}</div>
      </div>
    </div>
  );
}
