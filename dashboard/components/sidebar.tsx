"use client";

import { useTranslations, useLocale } from "next-intl";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { usePathname as useNextPathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Home, Plus, Activity, GitGraph, Users } from "lucide-react";
import { listProjects } from "@/lib/api";
import type { ProjectSummary } from "@/lib/api";
import { AddProjectModal } from "@/components/add-project-modal";
import { routing, LOCALE_LABELS, type Locale } from "@/i18n/routing";

export function Sidebar() {
  const t = useTranslations("Sidebar");
  const locale = useLocale() as Locale;
  // Localized pathname has NO locale prefix → active-link checks keep working.
  const pathname = usePathname();
  // Raw pathname (with locale prefix) is needed for the project-id regex.
  const rawPathname = useNextPathname();
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary["project"][]>([]);
  const [showAddModal, setShowAddModal] = useState(false);

  function refreshProjects() {
    listProjects().then((data) => setProjects(data.projects || []));
  }

  useEffect(() => { refreshProjects(); }, []);

  // Detect active project from the raw (prefixed) pathname.
  const projectMatch = rawPathname.match(/\/projects\/([^/]+)/);
  const activeProjectId = projectMatch ? projectMatch[1] : null;

  function switchLocale(next: Locale) {
    // router.replace keeps the current path and swaps the locale segment.
    router.replace(pathname, { locale: next });
  }

  return (
    <>
      <aside className="w-64 border-e border-zinc-800 bg-zinc-950 min-h-screen p-4 flex flex-col">
        <div className="mb-6 flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/loom-mark.svg"
              alt=""
              aria-hidden="true"
              className="h-8 w-8 shrink-0"
            />
            <div>
              <h1 className="text-lg font-bold text-zinc-100 leading-tight">{t("brand")}</h1>
              <p className="text-xs text-zinc-500">{t("subtitle")}</p>
            </div>
          </div>
          {/* Locale switcher: EN / ع */}
          <div className="flex items-center rounded-md border border-zinc-800 overflow-hidden text-[11px]">
            {routing.locales.map((l) => (
              <button
                key={l}
                onClick={() => switchLocale(l)}
                className={`px-2 py-1 transition-colors ${
                  locale === l
                    ? "bg-zinc-700 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
                aria-pressed={locale === l}
              >
                {LOCALE_LABELS[l]}
              </button>
            ))}
          </div>
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
            {t("navProjects")}
          </Link>

          {projects.length > 0 && (
            <>
              <div className="text-[10px] font-semibold text-zinc-600 uppercase px-3 pt-4 pb-1">
                {t("trackedProjects")}
              </div>
              {projects.map((p) => {
                const active = pathname.startsWith(`/projects/${p.project_id}`);
                return (
                  <div key={p.project_id}>
                    <Link
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
                    {/* Sub-navigation when this project is active */}
                    {active && (
                      <div className="ms-4 mt-0.5 mb-1 space-y-0.5">
                        <Link
                          href={`/projects/${p.project_id}`}
                          className={`flex items-center gap-2 px-3 py-1.5 rounded text-[11px] transition-colors ${
                            pathname === `/projects/${p.project_id}`
                              ? "text-zinc-200 bg-zinc-800/50"
                              : "text-zinc-500 hover:text-zinc-300"
                          }`}
                        >
                          <Activity className="w-3 h-3" /> {t("overview")}
                        </Link>
                        <Link
                          href={`/projects/${p.project_id}/graph`}
                          className={`flex items-center gap-2 px-3 py-1.5 rounded text-[11px] transition-colors ${
                            pathname.includes("/graph")
                              ? "text-zinc-200 bg-zinc-800/50"
                              : "text-zinc-500 hover:text-zinc-300"
                          }`}
                        >
                          <GitGraph className="w-3 h-3" /> {t("graph")}
                        </Link>
                        <Link
                          href={`/projects/${p.project_id}/agents`}
                          className={`flex items-center gap-2 px-3 py-1.5 rounded text-[11px] transition-colors ${
                            pathname.includes("/agents")
                              ? "text-zinc-200 bg-zinc-800/50"
                              : "text-zinc-500 hover:text-zinc-300"
                          }`}
                        >
                          <Users className="w-3 h-3" /> {t("agents")}
                        </Link>
                      </div>
                    )}
                  </div>
                );
              })}
            </>
          )}

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 w-full mt-2 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t("addProject")}
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
