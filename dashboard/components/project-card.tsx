"use client";

import { useTranslations, useFormatter } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/time-ago";

interface ProjectCardProps {
  project: {
    project_id: string;
    project_name: string;
    node_count: number;
    edge_count: number;
    community_count: number;
    active_agents: number;
    last_graph_update: string | null;
  };
}

export function ProjectCard({ project }: ProjectCardProps) {
  const t = useTranslations("ProjectCard");
  const tTime = useTranslations("Common.timeAgo");
  const format = useFormatter();

  const updated = timeAgo(project.last_graph_update, tTime);

  return (
    <Link href={`/projects/${project.project_id}`}>
      <Card className="bg-zinc-900 border-zinc-800 hover:border-zinc-700 transition-colors cursor-pointer">
        <CardHeader>
          <CardTitle className="text-zinc-100">{project.project_name}</CardTitle>
          <CardDescription className="text-zinc-500">{project.project_id}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 text-sm">
            <div>
              <span className="text-emerald-400 font-mono">
                {format.number(project.node_count)}
              </span>
              <span className="text-zinc-600 ms-1">{t("nodes")}</span>
            </div>
            <div>
              <span className="text-blue-400 font-mono">
                {format.number(project.edge_count)}
              </span>
              <span className="text-zinc-600 ms-1">{t("edges")}</span>
            </div>
            <div>
              <span className="text-purple-400 font-mono">
                {format.number(project.community_count)}
              </span>
              <span className="text-zinc-600 ms-1">{t("communities")}</span>
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            {project.active_agents > 0 ? (
              <Badge variant="default" className="bg-emerald-900 text-emerald-300 text-xs">
                {t("agentsActive", { count: project.active_agents })}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-zinc-600 text-xs">
                {t("noAgents")}
              </Badge>
            )}
            <span className="text-xs text-zinc-600 self-center">{t("updated", { timeAgo: updated })}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
