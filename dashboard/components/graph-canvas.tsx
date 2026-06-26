"use client";

import dynamic from "next/dynamic";

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  community: number;
  file: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
}

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeSelect?: (node: GraphNode) => void;
  highlightedNodes?: Set<string>;
  visibleCommunities?: Set<string>;
  showEdges?: boolean;
}

// Reagraph renders with Three.js/WebGL, which has no server-side equivalent and
// throws during Next's SSR pass. Loading it through next/dynamic with ssr:false
// (legal here because this is a Client Component) keeps the WebGL renderer and
// the entire reagraph/three dependency chain out of the server bundle.
const GraphCanvasReagraph = dynamic(
  () => import("./graph-canvas-reagraph"),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center w-full h-full text-sm text-zinc-600">
        Loading graph…
      </div>
    ),
  },
);

export function GraphCanvas(props: GraphCanvasProps) {
  return (
    <div
      className="w-full h-full bg-zinc-950 rounded-lg relative"
      style={{ minHeight: "500px" }}
    >
      <GraphCanvasReagraph {...props} />
    </div>
  );
}
