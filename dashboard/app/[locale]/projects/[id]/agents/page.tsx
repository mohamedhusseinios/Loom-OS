"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { getProject, listDispatches } from "@/lib/api";
import type { ProjectSummary } from "@/lib/api";
import { AgentCard } from "@/components/agent-card";
import { AgentWiring } from "@/components/agent-wiring";
import { DispatchModal } from "@/components/dispatch-modal";
import { DispatchHistory } from "@/components/dispatch-history";
import { Button } from "@/components/ui/button";
import { useWebSocket } from "@/lib/use-websocket";
import { Send } from "lucide-react";

export default function AgentManagementPage() {
  const t = useTranslations("AgentsPage");
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ProjectSummary | null>(null);
  const [dispatches, setDispatches] = useState<
    Awaited<ReturnType<typeof listDispatches>>["dispatches"]
  >([]);
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

  if (loading) return <div className="text-zinc-500">{t("loading")}</div>;
  if (!data) return <div className="text-zinc-500">{t("notFound")}</div>;

  const { agents } = data;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">{t("heading")}</h2>
          <p className="text-sm text-zinc-500">
            {t("agentCount", { count: agents.length })}
          </p>
        </div>
        {agents.length > 0 && (
          <Button onClick={() => setShowDispatch(true)} size="sm">
            <Send className="w-3.5 h-3.5 me-2" /> {t("dispatchTask")}
          </Button>
        )}
      </div>

      <div className="space-y-3 mb-8">
        {agents.length === 0 ? (
          <p className="text-sm text-zinc-600">{t("empty", { path: "~/.agentic-os/inbox/" })}</p>
        ) : (
          agents.map((a) => <AgentCard key={a.agent_id} agent={a} />)
        )}
      </div>

      <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">{t("agentWiring")}</h3>
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-8">
        <AgentWiring agents={agents} dispatches={dispatches} />
      </div>

      <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">{t("dispatchHistory")}</h3>
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
