"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { getProject } from "@/lib/api";
import type { ProjectSummary } from "@/lib/api";
import { GraphStats } from "@/components/graph-stats";
import { AgentBadge } from "@/components/agent-badge";
import { ActivityFeed } from "@/components/activity-feed";
import { Button } from "@/components/ui/button";
import { ArrowRight, Users } from "lucide-react";

export default function ProjectDetailPage() {
  const t = useTranslations("ProjectDetail");
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getProject(id)
      .then(setData)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="text-zinc-500">{t("loading")}</div>;
  if (!data) return <div className="text-zinc-500">{t("notFound")}</div>;

  const { project, graph, agents } = data;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">{project.project_name}</h2>
          <p className="text-sm text-zinc-500">{project.project_path}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href={`/projects/${id}/agents`}>
            <Button variant="outline" size="sm">
              <Users className="w-3 h-3 me-1" /> {t("agents")}
            </Button>
          </Link>
          <Link href={`/projects/${id}/graph`}>
            <Button variant="outline" size="sm">
              {t("graphExplorer")} <ArrowRight className="w-3 h-3 ms-2 rtl:rotate-180" />
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">{t("graphOverview")}</h3>
          {graph ? (
            <GraphStats stats={graph} />
          ) : (
            <p className="text-zinc-600 text-sm">{t("noGraph")}</p>
          )}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">{t("agents")}</h3>
          {agents.length === 0 ? (
            <p className="text-zinc-600 text-sm">{t("noAgents")}</p>
          ) : (
            <div className="divide-y divide-zinc-800">
              {agents.map((a) => (
                <AgentBadge key={a.agent_id} agent={a} />
              ))}
            </div>
          )}
        </div>
        <div className="lg:col-span-2">
          <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">{t("liveActivity")}</h3>
          <ActivityFeed projectId={id} />
        </div>
      </div>
    </div>
  );
}
