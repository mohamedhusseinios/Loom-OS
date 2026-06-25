"use client";

import { useEffect, useRef } from "react";
import cytoscape, { Core, EventObject } from "cytoscape";
import coseBilkent from "cytoscape-cose-bilkent";

cytoscape.use(coseBilkent);

const COMMUNITY_COLORS = [
  "#4ade80", "#60a5fa", "#c084fc", "#f59e0b", "#ec4899",
  "#34d399", "#818cf8", "#fbbf24", "#f472b6", "#a78bfa",
];

interface GraphCanvasProps {
  nodes: { id: string; label: string; kind: string; community: number; file: string }[];
  edges: { source: string; target: string; kind: string }[];
  onNodeSelect?: (node: { id: string; label: string; kind: string; community: number; file: string }) => void;
  highlightedNodes?: Set<string>;
  visibleCommunities?: Set<string>;
  showEdges?: boolean;
}

export function GraphCanvas({
  nodes,
  edges,
  onNodeSelect,
  highlightedNodes,
  visibleCommunities,
  showEdges = true,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#27272a",
            label: "data(label)",
            "font-size": "9px",
            color: "#a1a1aa",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 4,
            width: 12,
            height: 12,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": "#3f3f46",
            "curve-style": "bezier",
            opacity: 0.4,
          },
        },
        {
          selector: "node.highlighted",
          style: {
            "background-color": "#f59e0b",
            "border-color": "#fbbf24",
            "border-width": 2,
          },
        },
        {
          selector: "edge.highlighted",
          style: {
            "line-color": "#f59e0b",
            width: 2,
            opacity: 0.8,
          },
        },
      ],
      layout: {
        name: "cose-bilkent",
        animate: false as any,
        gravity: 0.4,
        idealEdgeLength: 100,
        nodeRepulsion: 8000,
      } as any,
    });

    cy.on("tap", "node", (evt: EventObject) => {
      const node = evt.target;
      onNodeSelect?.({
        id: node.id(),
        label: node.data("label"),
        kind: node.data("kind"),
        community: node.data("community"),
        file: node.data("file"),
      });
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.elements().remove();

    nodes.forEach((n) => {
      const colorIdx = (n.community || 0) % COMMUNITY_COLORS.length;
      cy.add({
        group: "nodes",
        data: {
          id: n.id,
          label: n.label,
          kind: n.kind,
          community: n.community,
          file: n.file,
        },
        style: {
          "background-color": COMMUNITY_COLORS[colorIdx],
        },
      });
    });

    if (showEdges) {
      edges.forEach((e) => {
        cy.add({
          group: "edges",
          data: {
            id: `${e.source}->${e.target}`,
            source: e.source,
            target: e.target,
            kind: e.kind,
          },
        });
      });
    }

    cy.layout({
      name: "cose-bilkent",
      animate: true as any,
      animationDuration: 500,
      gravity: 0.4,
      idealEdgeLength: 100,
      nodeRepulsion: 8000,
    } as any).run();
  }, [nodes, edges, showEdges]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !visibleCommunities) return;

    cy.nodes().forEach((node) => {
      const community = String(node.data("community"));
      if (visibleCommunities.has(community)) {
        node.style("display", "element");
      } else {
        node.style("display", "none");
      }
    });
  }, [visibleCommunities]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !highlightedNodes) return;

    cy.elements().removeClass("highlighted");

    if (highlightedNodes.size === 0) return;

    highlightedNodes.forEach((nodeId) => {
      const node = cy.getElementById(nodeId);
      if (node.length > 0) {
        node.addClass("highlighted");
        node.connectedEdges().addClass("highlighted");
      }
    });
  }, [highlightedNodes]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full bg-zinc-950 rounded-lg"
      style={{ minHeight: "500px" }}
    />
  );
}
