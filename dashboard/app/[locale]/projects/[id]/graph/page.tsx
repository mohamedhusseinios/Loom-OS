"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { getGraphTopology, getGraphCommunities, getGraphFlows, queryGraph } from "@/lib/api";
import { GraphCanvas } from "@/components/graph-canvas";
import { GraphControls } from "@/components/graph-controls";
import { NodeDetail } from "@/components/node-detail";
import { useWebSocket } from "@/lib/use-websocket";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Loader2 } from "lucide-react";

export default function GraphExplorerPage() {
  const { id } = useParams<{ id: string }>();
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [communities, setCommunities] = useState<any[]>([]);
  const [flows, setFlows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<any>(null);
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
      setVisibleCommunities(new Set((comms.communities || []).map((c: any) => String(c.id))));
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
    const flow = flows.find((f: any) => f.id === flowId);
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
      .filter((n: any) => n.label.toLowerCase().includes(q.toLowerCase()))
      .map((n: any) => n.id);
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
    return <div className="flex items-center justify-center h-96 text-zinc-500">Loading graph...</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-xl font-bold">Graph Explorer</h2>
          <p className="text-xs text-zinc-500">
            {nodes.length} nodes · {edges.length} edges · {communities.length} communities
          </p>
        </div>
        <form onSubmit={handleNLQuery} className="flex gap-2">
          <Input
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            placeholder="Ask about the codebase..."
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
              No graph data yet. Agents need to register and build the graph.
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
