"use client";

import { useMemo, useRef } from "react";
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

export default function GraphCanvasReagraph({
  nodes,
  edges,
  onNodeSelect,
  highlightedNodes,
  visibleCommunities,
  showEdges = true,
}: GraphCanvasProps) {
  const ref = useRef<GraphCanvasRef | null>(null);

  // Map domain nodes -> reagraph nodes, filtering by community visibility.
  const reaNodes = useMemo<ReaNode[]>(() => {
    return nodes
      .filter(
        (n) =>
          !visibleCommunities || visibleCommunities.has(String(n.community)),
      )
      .map((n) => ({
        id: n.id,
        label: n.label,
        fill: COMMUNITY_COLORS[(n.community || 0) % COMMUNITY_COLORS.length],
        // `data.community` is what clusterAttribute groups on; kind/file feed
        // the node-detail panel via onNodeSelect below.
        data: { kind: n.kind, community: n.community, file: n.file },
      }));
  }, [nodes, visibleCommunities]);

  const visibleIds = useMemo(
    () => new Set(reaNodes.map((n) => n.id)),
    [reaNodes],
  );

  // Drop edges whose endpoints are hidden; an empty list hides all edges.
  const reaEdges = useMemo<ReaEdge[]>(() => {
    if (!showEdges) return [];
    return edges
      .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
      .map((e) => ({
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        label: e.kind,
      }));
  }, [edges, visibleIds, showEdges]);

  // `actives` highlights the given nodes + their edges and dims the rest —
  // this powers both text search and flow highlighting from the page.
  const actives = useMemo(
    () => (highlightedNodes ? Array.from(highlightedNodes) : []),
    [highlightedNodes],
  );

  return (
    <ReagraphCanvas
      ref={ref}
      nodes={reaNodes}
      edges={reaEdges}
      actives={actives}
      theme={loomTheme}
      layoutType="forceDirected2d"
      labelType="nodes"
      draggable
      clusterAttribute="community"
      sizingType="centrality"
      onNodeClick={(node) => {
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
  );
}
