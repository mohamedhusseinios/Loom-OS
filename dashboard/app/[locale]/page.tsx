"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { listProjects } from "@/lib/api";
import type { ProjectSummary } from "@/lib/api";
import { ProjectCard } from "@/components/project-card";
import { AddProjectModal } from "@/components/add-project-modal";
import { useWebSocket } from "@/lib/use-websocket";
import { Plus } from "lucide-react";

export default function ProjectsPage() {
  const t = useTranslations("ProjectsPage");
  const [projects, setProjects] = useState<ProjectSummary["project"][]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const { lastEvent } = useWebSocket();

  function refresh() {
    listProjects()
      .then((data) => setProjects(data.projects || []))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, []);

  useEffect(() => {
    if (lastEvent && ["graph:updated", "project:created", "project:deleted"].includes(lastEvent.event)) {
      refresh();
    }
  }, [lastEvent]);

  if (loading) {
    return <div className="text-zinc-500">{t("loading")}</div>;
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">{t("heading")}</h2>
      {projects.length === 0 ? (
        <div className="text-zinc-500">
          <p>{t("empty")}</p>
          <p className="text-sm mt-2">
            {t("emptyHint")}{" "}
            <code className="text-zinc-400">~/.agentic-os/inbox/</code>
          </p>
          <button
            onClick={() => setShowAddModal(true)}
            className="text-sm mt-3 text-blue-400 hover:text-blue-300"
          >
            + {t("addFirst")}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <ProjectCard key={p.project_id} project={p} />
          ))}
          <button
            onClick={() => setShowAddModal(true)}
            className="bg-zinc-900 border-2 border-dashed border-zinc-800 hover:border-zinc-700 rounded-xl p-6 flex flex-col items-center justify-center gap-2 text-zinc-600 hover:text-zinc-400 transition-colors min-h-[160px]"
          >
            <Plus className="w-8 h-8" />
            <span className="text-sm">{t("add")}</span>
          </button>
        </div>
      )}

      <AddProjectModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={refresh}
      />
    </div>
  );
}
