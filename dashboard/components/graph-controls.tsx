"use client";

import { useTranslations } from "next-intl";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";
import type { GraphLayout } from "@/components/graph-canvas";

// value -> i18n key for the layouts we surface in the dropdown.
const LAYOUTS: { value: GraphLayout; labelKey: string }[] = [
  { value: "forceDirected2d", labelKey: "layoutForce2d" },
  { value: "forceDirected3d", labelKey: "layoutForce3d" },
  { value: "circular2d", labelKey: "layoutCircular" },
  { value: "concentric2d", labelKey: "layoutConcentric" },
  { value: "treeTd2d", labelKey: "layoutTree" },
  { value: "radialOut2d", labelKey: "layoutRadial" },
  { value: "hierarchicalTd", labelKey: "layoutHierarchical" },
];

interface CommunityInfo {
  id: string;
  name: string;
  size: number;
}

interface FlowInfo {
  id: string;
  name: string;
  criticality: number;
  node_ids: string[];
}

interface GraphControlsProps {
  communities: CommunityInfo[];
  flows: FlowInfo[];
  visibleCommunities: Set<string>;
  onToggleCommunity: (id: string) => void;
  selectedFlow: string | null;
  onSelectFlow: (id: string | null) => void;
  showEdges: boolean;
  onToggleEdges: () => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  selectedLayout: GraphLayout;
  onSelectLayout: (layout: GraphLayout) => void;
}

const COMMUNITY_COLORS = [
  "bg-emerald-900 text-emerald-300",
  "bg-blue-900 text-blue-300",
  "bg-purple-900 text-purple-300",
  "bg-amber-900 text-amber-300",
  "bg-pink-900 text-pink-300",
];

export function GraphControls({
  communities,
  flows,
  visibleCommunities,
  onToggleCommunity,
  selectedFlow,
  onSelectFlow,
  showEdges,
  onToggleEdges,
  searchQuery,
  onSearchChange,
  selectedLayout,
  onSelectLayout,
}: GraphControlsProps) {
  const t = useTranslations("GraphControls");
  return (
    <div className="w-[220px] bg-zinc-900 border-e border-zinc-800 p-3 overflow-y-auto h-full flex-shrink-0">
      <div className="relative mb-4">
        <Search className="w-3.5 h-3.5 absolute start-2.5 top-1/2 -translate-y-1/2 text-zinc-500" />
        <Input
          placeholder={t("searchPlaceholder")}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="ps-8 bg-zinc-800 border-zinc-700 text-zinc-200 text-xs h-8"
        />
      </div>

      <div className="mb-4">
        <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">{t("communities")}</h4>
        <div className="flex flex-wrap gap-1.5">
          {communities.map((c, i) => {
            const visible = visibleCommunities.has(c.id);
            const colorClass = COMMUNITY_COLORS[i % COMMUNITY_COLORS.length];
            return (
              <button
                key={c.id}
                onClick={() => onToggleCommunity(c.id)}
                className={`text-[10px] px-2 py-1 rounded-full transition-opacity ${
                  visible ? colorClass + " opacity-100" : "bg-zinc-800 text-zinc-600 opacity-60"
                }`}
              >
                {c.name} <span className="opacity-60">{c.size}</span>
              </button>
            );
          })}
        </div>
      </div>

      {flows.length > 0 && (
        <div className="mb-4">
          <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">{t("flows")}</h4>
          <div className="space-y-0.5">
            <button
              onClick={() => onSelectFlow(null)}
              className={`w-full text-start text-[11px] px-2 py-1 rounded ${
                !selectedFlow ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {t("showAll")}
            </button>
            {flows.slice(0, 10).map((f) => (
              <button
                key={f.id}
                onClick={() => onSelectFlow(f.id)}
                className={`w-full text-start text-[11px] px-2 py-1 rounded truncate ${
                  selectedFlow === f.id ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {f.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mb-4">
        <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">{t("layout")}</h4>
        <select
          value={selectedLayout}
          onChange={(e) => onSelectLayout(e.target.value as GraphLayout)}
          className="w-full bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded h-8 px-2"
        >
          {LAYOUTS.map((l) => (
            <option key={l.value} value={l.value}>
              {t(l.labelKey)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <h4 className="text-[10px] font-semibold text-zinc-500 uppercase mb-2">{t("view")}</h4>
        <label className="flex items-center gap-2 text-[11px] text-zinc-400 cursor-pointer mb-1.5">
          <input
            type="checkbox"
            checked={showEdges}
            onChange={onToggleEdges}
            className="accent-emerald-500 w-3 h-3"
          />
          {t("showEdges")}
        </label>
      </div>
    </div>
  );
}
