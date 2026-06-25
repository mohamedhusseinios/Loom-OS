"use client";

import { useEffect, useState } from "react";
import { listProjects } from "@/lib/api";
import { ProjectCard } from "@/components/project-card";
import { useWebSocket } from "@/lib/use-websocket";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    listProjects()
      .then((data) => setProjects(data.projects || []))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (lastEvent?.event === "graph:updated") {
      listProjects().then((data) => setProjects(data.projects || []));
    }
  }, [lastEvent]);

  if (loading) {
    return <div className="text-zinc-500">Loading projects...</div>;
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Projects</h2>
      {projects.length === 0 ? (
        <div className="text-zinc-500">
          <p>No projects tracked yet.</p>
          <p className="text-sm mt-2">
            Agents will appear here when they register by writing to{" "}
            <code className="text-zinc-400">~/.agentic-os/inbox/</code>
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <ProjectCard key={p.project_id} project={p} />
          ))}
        </div>
      )}
    </div>
  );
}
