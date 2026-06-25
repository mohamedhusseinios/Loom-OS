"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Home, Plus } from "lucide-react";
import { listProjects } from "@/lib/api";
import { AddProjectModal } from "@/components/add-project-modal";

export function Sidebar() {
  const pathname = usePathname();
  const [projects, setProjects] = useState<any[]>([]);
  const [showAddModal, setShowAddModal] = useState(false);

  function refreshProjects() {
    listProjects().then((data) => setProjects(data.projects || []));
  }

  useEffect(() => {
    refreshProjects();
  }, []);

  return (
    <>
      <aside className="w-64 border-r border-zinc-800 bg-zinc-950 min-h-screen p-4 flex flex-col">
        <div className="mb-6">
          <h1 className="text-lg font-bold text-zinc-100">Agentic OS</h1>
          <p className="text-xs text-zinc-500">Agent Memory Fabric</p>
        </div>
        <nav className="space-y-1 flex-1">
          <Link
            href="/"
            className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
              pathname === "/"
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
            }`}
          >
            <Home className="w-4 h-4" />
            Projects
          </Link>

          {projects.length > 0 && (
            <>
              <div className="text-[10px] font-semibold text-zinc-600 uppercase px-3 pt-4 pb-1">
                Tracked Projects
              </div>
              {projects.map((p) => {
                const active = pathname.startsWith(`/projects/${p.project_id}`);
                return (
                  <Link
                    key={p.project_id}
                    href={`/projects/${p.project_id}`}
                    className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                      active
                        ? "bg-zinc-800 text-zinc-100"
                        : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
                    }`}
                  >
                    <span className="flex-1 truncate">{p.project_name}</span>
                    {p.active_agents > 0 && (
                      <span className="text-[10px] bg-emerald-900 text-emerald-300 px-1.5 py-0.5 rounded-full font-mono">
                        {p.active_agents}
                      </span>
                    )}
                  </Link>
                );
              })}
            </>
          )}

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 w-full mt-2 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Project
          </button>
        </nav>
      </aside>

      <AddProjectModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={refreshProjects}
      />
    </>
  );
}
