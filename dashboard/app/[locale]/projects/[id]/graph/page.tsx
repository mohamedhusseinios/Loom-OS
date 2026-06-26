"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { getGraphTopology, getGraphCommunities, getGraphFlows, queryGraph } from "@/lib/api";
import type { GraphTopology, CommunityInfo, FlowInfo } from "@/lib/api";
import { GraphCanvas } from "@/components/graph-canvas";
import { GraphControls } from "@/components/graph-controls";
import { NodeDetail } from "@/components/node-detail";
import { useWebSocket } from "@/lib/use-websocket";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Loader2 } from "lucide-react";

type GraphNode = GraphTopology["nodes"][number];

export default function GraphExplorerPage() {
  const t = useTranslations("GraphExplorer");
  const { id } = useParams<{ id: string }>();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphTopology["edges"]>([]);
  const [communities, setCommunities] = useState<CommunityInfo[]>([]);
  const [flows, setFlows] = useState<FlowInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [visibleCommunities, setVisibleCommunities] = useState<Set<string>>(new Set());
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [showEdges, setShowEdges] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [nlQuery, setNlQuery] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [topo, comms, flws] = await Promise.all([
        getGraphTopology(id),
        getGraphCommunities(id),
        getGraphFlows(id),
      ]);
      setNodes(topo.nodes || []);
      setEdges(topo.edges || []);
      setCommunities(comms.communities || []);
      setFlows(flws.flows || []);
      setVisibleCommunities(new Set((comms.communities || []).map((c) => String(c.id))));
    } catch {
      // graph not built yet
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (event.event === "graph:updated") {
        loadData();
      }
    });
  }, [id, subscribe, loadData]);

  function handleToggleCommunity(communityId: string) {
    setVisibleCommunities((prev) => {
      const next = new Set(prev);
      if (next.has(communityId)) next.delete(communityId);
      else next.add(communityId);
      return next;
    });
  }

  function handleSelectFlow(flowId: string | null) {
    setSelectedFlow(flowId);
    if (!flowId) {
      setHighlightedNodes(new Set());
      return;
    }
    const flow = flows.find((f) => f.id === flowId);
    if (flow) {
      setHighlightedNodes(new Set(flow.node_ids));
    }
  }

  function handleSearchChange(q: string) {
    setSearchQuery(q);
    if (!q.trim()) {
      setHighlightedNodes(new Set());
      return;
    }
    const matching = nodes
      .filter((n) => n.label.toLowerCase().includes(q.toLowerCase()))
      .map((n) => n.id);
    setHighlightedNodes(new Set(matching));
  }

  async function handleNLQuery(e: React.FormEvent) {
    e.preventDefault();
    if (!nlQuery.trim()) return;
    setNlLoading(true);
    try {
      await queryGraph(id, nlQuery);
    } catch {} finally {
      setNlLoading(false);
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-96 text-zinc-500">{t("loading")}</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-xl font-bold">{t("heading")}</h2>
          <p className="text-xs text-zinc-500">
            {t("stats", { nodes: nodes.length, edges: edges.length, communities: communities.length })}
          </p>
        </div>
        <form onSubmit={handleNLQuery} className="flex gap-2">
          <Input
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            className="bg-zinc-900 border-zinc-700 text-zinc-200 text-sm w-64"
          />
          <Button type="submit" size="sm" disabled={nlLoading}>
            {nlLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          </Button>
        </form>
      </div>

      <div className="flex flex-1 gap-0 border border-zinc-800 rounded-lg overflow-hidden">
        <GraphControls
          communities={communities}
          flows={flows}
          visibleCommunities={visibleCommunities}
          onToggleCommunity={handleToggleCommunity}
          selectedFlow={selectedFlow}
          onSelectFlow={handleSelectFlow}
          showEdges={showEdges}
          onToggleEdges={() => setShowEdges(!showEdges)}
          searchQuery={searchQuery}
          onSearchChange={handleSearchChange}
        />

        <div className="flex-1 relative">
          {nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full text-sm text-zinc-600">
              {t("empty")}
            </div>
          ) : (
            <GraphCanvas
              nodes={nodes}
              edges={edges}
              onNodeSelect={setSelectedNode}
              highlightedNodes={highlightedNodes}
              visibleCommunities={visibleCommunities}
              showEdges={showEdges}
            />
          )}
          <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
        </div>
      </div>
    </div>
  );
}
