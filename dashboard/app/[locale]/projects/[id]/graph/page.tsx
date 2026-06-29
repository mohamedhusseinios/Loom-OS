"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { getGraphTopology, getGraphCommunities, getGraphFlows, queryGraph, rebuildGraph, getProject, getExtractedEdges } from "@/lib/api";
import type { GraphTopology, CommunityInfo, FlowInfo } from "@/lib/api";
import { GraphCanvas, type GraphLayout } from "@/components/graph-canvas";
import { GraphControls } from "@/components/graph-controls";
import { NodeDetail } from "@/components/node-detail";
import { useWebSocket } from "@/lib/use-websocket";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Loader2, Hammer, CheckCircle2, XCircle } from "lucide-react";

type GraphNode = GraphTopology["nodes"][number];

export default function GraphExplorerPage() {
  const t = useTranslations("GraphExplorer");
  const { id } = useParams<{ id: string }>();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphTopology["edges"]>([]);
  const [communities, setCommunities] = useState<CommunityInfo[]>([]);
  const [flows, setFlows] = useState<FlowInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [hasAgents, setHasAgents] = useState(false);
  const [buildTaskId, setBuildTaskId] = useState<string | null>(null);
  const [buildAgent, setBuildAgent] = useState<string | null>(null);
  const [buildStatus, setBuildStatus] = useState<"building" | "completed" | "failed" | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [visibleCommunities, setVisibleCommunities] = useState<Set<string>>(new Set());
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [showEdges, setShowEdges] = useState(true);
  const [layout, setLayout] = useState<GraphLayout>("forceDirected2d");
  // Drill-down state for large graphs: null = community overview, an id =
  // that community's members. Ignored for small graphs (rendered in full).
  const [expandedCommunity, setExpandedCommunity] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [nlQuery, setNlQuery] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [topo, comms, flws, project] = await Promise.all([
        getGraphTopology(id),
        getGraphCommunities(id),
        getGraphFlows(id),
        getProject(id),
      ]);
      const topoNodes = topo.nodes || [];
      setNodes(topoNodes);
      setExpandedCommunity(null); // a fresh graph resets any drill-down
      setCommunities(comms.communities || []);
      setFlows(flws.flows || []);
      setVisibleCommunities(new Set((comms.communities || []).map((c) => String(c.id))));
      setHasAgents((project.agents || []).length > 0);

      // Overlay LLM-extracted edges on top of the structural topology edges.
      // The endpoint may not exist yet on older daemons — fail silently.
      const topologyEdges = topo.edges || [];
      try {
        const { edges: extractedEdges } = await getExtractedEdges(id);
        const nodeIds = new Set(topoNodes.map((n) => n.id));
        const llmEdges = extractedEdges.flatMap((e) =>
          e.relationships.map(([verb, target]) => ({
            source: e.name,
            target,
            kind: `${verb} (llm)`,
          })),
        );
        const validLlmEdges = llmEdges.filter(
          (e) => nodeIds.has(e.source) && nodeIds.has(e.target),
        );
        setEdges([...topologyEdges, ...validLlmEdges]);
      } catch {
        // Extracted-edges endpoint unavailable — use topology edges only.
        setEdges(topologyEdges);
      }
    } catch {
      // graph not built yet
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  // Listen for graph:updated (direct mode) and task:completed / task:failed (agent mode).
  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (event.event === "graph:updated") {
        loadData();
        setBuilding(false);
        // A failed build still emits graph:updated (with status="failed") so
        // the dashboard refreshes — don't report it as a successful build.
        setBuildStatus(event.data?.status === "failed" ? "failed" : "completed");
      }
      if (event.event === "task:completed" && event.data?.task_id === buildTaskId) {
        setBuildStatus("completed");
        // graph:updated will follow and trigger loadData.
      }
      if (event.event === "task:failed" && event.data?.task_id === buildTaskId) {
        setBuildStatus("failed");
        setBuilding(false);
      }
    });
  }, [id, subscribe, loadData, buildTaskId]);

  async function handleBuildGraph() {
    setBuilding(true);
    setBuildStatus("building");
    setBuildTaskId(null);
    setBuildAgent(null);
    try {
      const result = await rebuildGraph(id);
      if (result.mode === "agent" && result.task_id) {
        setBuildTaskId(result.task_id);
        setBuildAgent(result.agent || null);
      }
      // Fallback: if no WebSocket event arrives within 30 s, reload anyway.
      setTimeout(() => {
        loadData();
        setBuilding((prev) => { if (prev) return false; return prev; });
        setBuildStatus((prev) => prev === "building" ? null : prev);
      }, 30000);
    } catch {
      setBuilding(false);
      setBuildStatus("failed");
    }
  }

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
          {/* Task dispatch feedback banner */}
          {buildStatus === "building" && buildAgent && (
            <p className="text-xs text-amber-400 mt-1">
              {t("buildingVia", { agent: buildAgent })}
            </p>
          )}
          {buildStatus === "completed" && buildTaskId && (
            <p className="text-xs text-emerald-400 mt-1 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              {t("buildComplete")}
            </p>
          )}
          {buildStatus === "failed" && (
            <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
              <XCircle className="w-3 h-3" />
              {t("buildFailed")}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleBuildGraph}
            disabled={building || !hasAgents}
            title={!hasAgents ? t("buildDisabledNoAgents") : undefined}
          >
            {building ? (
              <>
                <Loader2 className="w-3.5 h-3.5 me-1 animate-spin" />
                {t("building")}
              </>
            ) : (
              <>
                <Hammer className="w-3.5 h-3.5 me-1" />
                {t("buildGraph")}
              </>
            )}
          </Button>
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
      </div>

      <div className="flex flex-1 gap-0 border border-zinc-800 rounded-lg overflow-hidden">
        {nodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-3 text-sm text-zinc-600">
            <p>{t("empty")}</p>
            {hasAgents && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleBuildGraph}
                disabled={building}
              >
                {building ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 me-1 animate-spin" />
                    {t("building")}
                  </>
                ) : (
                  <>
                    <Hammer className="w-3.5 h-3.5 me-1" />
                    {t("buildGraph")}
                  </>
                )}
              </Button>
            )}
          </div>
        ) : (
          <>
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
              selectedLayout={layout}
              onSelectLayout={setLayout}
            />
            <div className="flex-1 relative">
              <GraphCanvas
                nodes={nodes}
                edges={edges}
                communities={communities}
                onNodeSelect={setSelectedNode}
                highlightedNodes={highlightedNodes}
                visibleCommunities={visibleCommunities}
                showEdges={showEdges}
                layout={layout}
                expandedCommunity={expandedCommunity}
                onExpandCommunity={setExpandedCommunity}
              />
              <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
