"use client";

import { useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import {
  GraphCanvas as ReagraphCanvas,
  darkTheme,
  type GraphCanvasRef,
  type GraphNode as ReaNode,
  type GraphEdge as ReaEdge,
  type Theme,
} from "reagraph";
import type { GraphCanvasProps } from "./graph-canvas";

// Per-community palette, kept in sync with the chips in graph-controls.tsx.
const COMMUNITY_COLORS = [
  "#4ade80", "#60a5fa", "#c084fc", "#f59e0b", "#ec4899",
  "#34d399", "#818cf8", "#fbbf24", "#f472b6", "#a78bfa",
];

// Reagraph is a WebGL/Three.js renderer tuned for hundreds-to-low-thousands of
// nodes. A real code graph can be 10k+ nodes, which saturates the main thread
// and freezes the tab, so we never hand reagraph the raw graph at that scale:
//   • <= DIRECT_RENDER_LIMIT nodes -> render everything ("direct").
//   • larger -> render one super-node per community ("overview"); clicking a
//     super-node drills into that community's members ("expanded").
// Each drill level is itself capped so the canvas stays responsive at any size.
const DIRECT_RENDER_LIMIT = 1200;
const MAX_SUPERNODES = 150;
const MAX_MEMBERS = 400;
const LABEL_THRESHOLD = 400; // hide per-node labels above this many rendered nodes
const COMMUNITY_PREFIX = "__community__:";

// Dark theme tuned to match the zinc-950 canvas the dashboard uses elsewhere.
const loomTheme: Theme = {
  ...darkTheme,
  canvas: { background: "#09090b" },
  node: {
    ...darkTheme.node,
    label: {
      ...darkTheme.node.label,
      color: "#a1a1aa",
      activeColor: "#fbbf24",
    },
  },
  edge: {
    ...darkTheme.edge,
    fill: "#3f3f46",
    activeFill: "#f59e0b",
  },
};

type ViewMode = "direct" | "overview" | "expanded";

export default function GraphCanvasReagraph({
  nodes,
  edges,
  communities = [],
  onNodeSelect,
  highlightedNodes,
  visibleCommunities,
  showEdges = true,
  layout = "forceDirected2d",
  expandedCommunity = null,
  onExpandCommunity,
}: GraphCanvasProps) {
  const t = useTranslations("GraphCanvas");
  const ref = useRef<GraphCanvasRef | null>(null);

  // Pick the render strategy from the graph size and drill state.
  const mode: ViewMode =
    nodes.length <= DIRECT_RENDER_LIMIT
      ? "direct"
      : expandedCommunity
        ? "expanded"
        : "overview";

  // node id -> community key (string). Feeds overview contraction + search.
  const nodeCommunity = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of nodes) m.set(n.id, String(n.community));
    return m;
  }, [nodes]);

  // Colour per community id, matching the sidebar chips' ordering so the
  // overview's super-node colours line up with the legend in graph-controls.
  const communityColor = useMemo(() => {
    const m = new Map<string, string>();
    communities.forEach((c, i) =>
      m.set(c.id, COMMUNITY_COLORS[i % COMMUNITY_COLORS.length]),
    );
    return m;
  }, [communities]);

  // Build the bounded node/edge set reagraph actually renders for this mode.
  const view = useMemo(() => {
    // --- direct: the whole graph, filtered by community visibility ---
    if (mode === "direct") {
      const rn: ReaNode[] = nodes
        .filter(
          (n) =>
            !visibleCommunities || visibleCommunities.has(String(n.community)),
        )
        .map((n) => ({
          id: n.id,
          label: n.label,
          fill: COMMUNITY_COLORS[(n.community || 0) % COMMUNITY_COLORS.length],
          data: { kind: n.kind, community: n.community, file: n.file },
        }));
      const ids = new Set(rn.map((n) => n.id));
      const re: ReaEdge[] = showEdges
        ? edges
            .filter((e) => ids.has(e.source) && ids.has(e.target))
            .map((e) => ({
              id: `${e.source}->${e.target}`,
              source: e.source,
              target: e.target,
              label: e.kind,
            }))
        : [];
      return { reaNodes: rn, reaEdges: re, shown: rn.length, total: nodes.length };
    }

    // --- expanded: members of one community, capped to the top by degree ---
    if (mode === "expanded" && expandedCommunity) {
      const members = nodes.filter(
        (n) => String(n.community) === expandedCommunity,
      );
      const memberIds = new Set(members.map((m) => m.id));
      const degree = new Map<string, number>();
      for (const e of edges) {
        if (memberIds.has(e.source) && memberIds.has(e.target)) {
          degree.set(e.source, (degree.get(e.source) || 0) + 1);
          degree.set(e.target, (degree.get(e.target) || 0) + 1);
        }
      }
      const shown = [...members]
        .sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0))
        .slice(0, MAX_MEMBERS);
      const shownIds = new Set(shown.map((m) => m.id));
      const rn: ReaNode[] = shown.map((n) => ({
        id: n.id,
        label: n.label,
        fill: COMMUNITY_COLORS[(n.community || 0) % COMMUNITY_COLORS.length],
        data: { kind: n.kind, community: n.community, file: n.file },
      }));
      const re: ReaEdge[] = showEdges
        ? edges
            .filter((e) => shownIds.has(e.source) && shownIds.has(e.target))
            .map((e) => ({
              id: `${e.source}->${e.target}`,
              source: e.source,
              target: e.target,
              label: e.kind,
            }))
        : [];
      return {
        reaNodes: rn,
        reaEdges: re,
        shown: shown.length,
        total: members.length,
      };
    }

    // --- overview: one super-node per visible community, capped by size ---
    const visible = communities
      .filter((c) => !visibleCommunities || visibleCommunities.has(c.id))
      .sort((a, b) => b.size - a.size);
    const shownC = visible.slice(0, MAX_SUPERNODES);
    const shownIds = new Set(shownC.map((c) => c.id));
    const rn: ReaNode[] = shownC.map((c) => ({
      id: COMMUNITY_PREFIX + c.id,
      label: `${c.name} (${c.size})`,
      fill: communityColor.get(c.id) ?? COMMUNITY_COLORS[0],
      data: { community: c.id },
    }));
    // Contract every cross-community edge into a weighted super-edge.
    const weights = new Map<string, number>();
    if (showEdges) {
      for (const e of edges) {
        const ca = nodeCommunity.get(e.source);
        const cb = nodeCommunity.get(e.target);
        if (!ca || !cb || ca === cb) continue;
        if (!shownIds.has(ca) || !shownIds.has(cb)) continue;
        const key = ca < cb ? `${ca}|${cb}` : `${cb}|${ca}`;
        weights.set(key, (weights.get(key) || 0) + 1);
      }
    }
    const re: ReaEdge[] = [...weights.entries()].map(([key, w]) => {
      const [a, b] = key.split("|");
      return {
        id: `c:${key}`,
        source: COMMUNITY_PREFIX + a,
        target: COMMUNITY_PREFIX + b,
        label: String(w),
      };
    });
    return {
      reaNodes: rn,
      reaEdges: re,
      shown: shownC.length,
      total: visible.length,
    };
  }, [
    mode,
    nodes,
    edges,
    communities,
    visibleCommunities,
    showEdges,
    expandedCommunity,
    nodeCommunity,
    communityColor,
  ]);

  // `actives` highlights nodes + their edges and dims the rest — this powers
  // both text search and flow highlighting. In overview mode the highlighted
  // node ids don't exist on the canvas, so map them up to their super-nodes.
  const actives = useMemo(() => {
    if (!highlightedNodes || highlightedNodes.size === 0) return [];
    if (mode === "overview") {
      const s = new Set<string>();
      for (const id of highlightedNodes) {
        const c = nodeCommunity.get(id);
        if (c) s.add(COMMUNITY_PREFIX + c);
      }
      return [...s];
    }
    return [...highlightedNodes];
  }, [highlightedNodes, mode, nodeCommunity]);

  const expandedName =
    mode === "expanded"
      ? communities.find((c) => c.id === expandedCommunity)?.name ??
        expandedCommunity
      : null;

  return (
    <>
      {/* Drill-down status + navigation. Hidden for small ("direct") graphs. */}
      {mode !== "direct" && (
        <div className="absolute top-2 start-2 z-10 flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-900/85 px-2.5 py-1.5 text-[11px] backdrop-blur">
          {mode === "expanded" ? (
            <>
              <button
                onClick={() => onExpandCommunity?.(null)}
                className="font-medium text-amber-400 hover:text-amber-300"
              >
                ← {t("overview")}
              </button>
              <span className="max-w-[200px] truncate font-medium text-zinc-300">
                {expandedName}
              </span>
              <span className="text-zinc-500">
                {t("nodesShown", { shown: view.shown, total: view.total })}
              </span>
            </>
          ) : (
            <>
              <span className="text-zinc-300">
                {t("communitiesShown", { shown: view.shown, total: view.total })}
              </span>
              <span className="text-zinc-500">· {t("drillHint")}</span>
            </>
          )}
        </div>
      )}
      <ReagraphCanvas
        ref={ref}
        nodes={view.reaNodes}
        edges={view.reaEdges}
        actives={actives}
        theme={loomTheme}
        layoutType={layout}
        // Labels are per-node WebGL meshes; suppress them when there are too
        // many to read anyway, which also keeps the frame budget in check.
        labelType={view.reaNodes.length > LABEL_THRESHOLD ? "none" : "nodes"}
        draggable
        // Cluster hulls only render on force-directed layouts, and only the
        // "direct" graph has real per-node communities to cluster on — overview
        // super-nodes and single-community members have nothing to group.
        clusterAttribute={
          mode === "direct" && layout.startsWith("forceDirected")
            ? "community"
            : undefined
        }
        sizingType="centrality"
        onNodeClick={(node) => {
          // In overview a node *is* a community: clicking it drills in.
          if (mode === "overview") {
            const cid = node.id.startsWith(COMMUNITY_PREFIX)
              ? node.id.slice(COMMUNITY_PREFIX.length)
              : node.id;
            onExpandCommunity?.(cid);
            return;
          }
          const data = (node.data ?? {}) as {
            kind?: string;
            community?: number;
            file?: string;
          };
          onNodeSelect?.({
            id: node.id,
            label: node.label ?? node.id,
            kind: data.kind ?? "",
            community: data.community ?? 0,
            file: data.file ?? "",
          });
        }}
      />
    </>
  );
}
