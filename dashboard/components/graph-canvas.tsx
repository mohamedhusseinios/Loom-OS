"use client";

import { Component, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import type { CommunityInfo } from "@/lib/api";

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

// Curated subset of reagraph's LayoutTypes that we surface in the UI. Every
// value here is assignable to reagraph's `layoutType` prop.
export type GraphLayout =
  | "forceDirected2d"
  | "forceDirected3d"
  | "circular2d"
  | "concentric2d"
  | "treeTd2d"
  | "radialOut2d"
  | "hierarchicalTd";

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  // Communities power the drill-down overview when the graph is too large to
  // render every node directly (see graph-canvas-reagraph.tsx).
  communities?: CommunityInfo[];
  onNodeSelect?: (node: GraphNode) => void;
  highlightedNodes?: Set<string>;
  visibleCommunities?: Set<string>;
  showEdges?: boolean;
  layout?: GraphLayout;
  // null = community overview; a community id = that community's members.
  expandedCommunity?: string | null;
  onExpandCommunity?: (id: string | null) => void;
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

// A reagraph render can throw — e.g. the tree/hierarchical/radial layouts build
// a node hierarchy and choke on the cyclic, disconnected graphs that code
// produces. Without a boundary, that throw unmounts the whole page (blank
// screen). We catch it and offer a way out; remounting via `key` (layout +
// expandedCommunity) clears the error whenever the user changes either.
class CanvasErrorBoundary extends Component<
  { children: ReactNode; title: string; resetLabel?: string; onReset?: () => void },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: unknown) {
    console.error("Graph canvas failed to render", error);
  }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="flex flex-col items-center justify-center w-full h-full gap-2 text-sm text-zinc-500">
        <p>{this.props.title}</p>
        {this.props.resetLabel && this.props.onReset && (
          <button
            onClick={this.props.onReset}
            className="text-xs text-amber-400 hover:text-amber-300"
          >
            ← {this.props.resetLabel}
          </button>
        )}
      </div>
    );
  }
}

export function GraphCanvas(props: GraphCanvasProps) {
  const t = useTranslations("GraphCanvas");
  return (
    <div
      className="w-full h-full bg-zinc-950 rounded-lg relative"
      style={{ minHeight: "500px" }}
    >
      <CanvasErrorBoundary
        key={`${props.layout}-${props.expandedCommunity}`}
        title={t("renderError")}
        resetLabel={props.expandedCommunity ? t("overview") : undefined}
        onReset={
          props.expandedCommunity
            ? () => props.onExpandCommunity?.(null)
            : undefined
        }
      >
        <GraphCanvasReagraph {...props} />
      </CanvasErrorBoundary>
    </div>
  );
}
