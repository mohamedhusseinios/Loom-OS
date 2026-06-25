"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { getProject, listDispatches } from "@/lib/api";
import { AgentCard } from "@/components/agent-card";
import { AgentWiring } from "@/components/agent-wiring";
import { DispatchModal } from "@/components/dispatch-modal";
import { DispatchHistory } from "@/components/dispatch-history";
import { Button } from "@/components/ui/button";
import { useWebSocket } from "@/lib/use-websocket";
import { Send } from "lucide-react";

export default function AgentManagementPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [dispatches, setDispatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showDispatch, setShowDispatch] = useState(false);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    try {
      const [projectData, dispatchData] = await Promise.all([
        getProject(id),
        listDispatches(id),
      ]);
      setData(projectData);
      setDispatches(dispatchData.dispatches || []);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (["agent:online", "agent:offline", "agent:dispatched", "task:completed"].includes(event.event)) {
        loadData();
      }
    });
  }, [id, subscribe, loadData]);

  if (loading) return <div className="text-zinc-500">Loading...</div>;
  if (!data) return <div className="text-zinc-500">Project not found</div>;

  const { agents } = data;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">Agents</h2>
          <p className="text-sm text-zinc-500">{agents.length} agent{agents.length !== 1 ? "s" : ""} registered</p>
        </div>
        {agents.length > 0 && (
          <Button onClick={() => setShowDispatch(true)} size="sm">
            <Send className="w-3.5 h-3.5 mr-2" /> Dispatch Task
          </Button>
        )}
      </div>

      <div className="space-y-3 mb-8">
        {agents.length === 0 ? (
          <p className="text-sm text-zinc-600">
            No agents registered yet. Agents appear when they write register.json to ~/.agentic-os/inbox/
          </p>
        ) : (
          agents.map((a: any) => <AgentCard key={a.agent_id} agent={a} />)
        )}
      </div>

      <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Agent Wiring</h3>
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-8">
        <AgentWiring agents={agents} dispatches={dispatches} />
      </div>

      <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Dispatch History</h3>
      <DispatchHistory dispatches={dispatches} />

      <DispatchModal
        open={showDispatch}
        onClose={() => setShowDispatch(false)}
        projectId={id}
        agents={agents}
        onDispatched={loadData}
      />
    </div>
  );
}
