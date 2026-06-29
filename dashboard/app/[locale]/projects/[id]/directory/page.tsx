"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { getProject } from "@/lib/api";
import type { ProjectSummary } from "@/lib/api";
import { AgentDirectory } from "@/components/agent-directory";
import { useWebSocket } from "@/lib/use-websocket";

export default function AgentDirectoryPage() {
  const t = useTranslations("AgentDirectory");
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const { subscribe } = useWebSocket();

  const loadData = useCallback(async () => {
    try {
      const projectData = await getProject(id);
      setData(projectData);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    return subscribe(`project:${id}`, (event) => {
      if (["agent:online", "agent:offline"].includes(event.event)) {
        loadData();
      }
    });
  }, [id, subscribe, loadData]);

  if (loading) return <div className="text-zinc-500">{t("loading")}</div>;
  if (!data) return <div className="text-zinc-500">{t("notFound")}</div>;

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold">{t("heading")}</h2>
        <p className="text-sm text-zinc-500">{t("subtitle", { count: data.agents.length })}</p>
      </div>
      <AgentDirectory projectId={id} agents={data.agents} />
    </div>
  );
}