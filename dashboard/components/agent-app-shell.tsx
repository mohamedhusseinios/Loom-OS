"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Loader2, Plus, Square, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePathname, useRouter } from "@/i18n/navigation";
import { useWebSocket } from "@/lib/use-websocket";
import {
  listProjects,
  listAgentTasks,
  listWorkers,
  stopWorker,
  previewImplement,
  implementTask,
  getAgentSettings,
  getAgentCostSummary,
  ImplementConflictError,
  type AgentCostSummary,
  type AgentTask,
  type ProjectSummary,
  type SelectionPreview,
} from "@/lib/api";
import { LoomAgentChat } from "@/components/loom-agent-chat";
import {
  ImplementPickerModal,
  type ImplementPickerNotice,
} from "@/components/implement-picker-modal";
import { AddProjectModal } from "@/components/add-project-modal";

type Project = ProjectSummary["project"];

function formatUsd(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function AgentAppShell() {
  const t = useTranslations("AgentApp");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { subscribe } = useWebSocket();
  const projectId = searchParams.get("project");
  const taskId = searchParams.get("task");

  const [projects, setProjects] = useState<Project[] | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [workerIds, setWorkerIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [cost, setCost] = useState<AgentCostSummary | null>(null);
  const [picker, setPicker] = useState<{ preview: SelectionPreview; notice: ImplementPickerNotice } | null>(null);
  const [metricsProjectId, setMetricsProjectId] = useState(projectId);
  const projectIdRef = useRef(projectId);
  if (metricsProjectId !== projectId) {
    setMetricsProjectId(projectId);
    setCost(null);
    setWorkerIds(new Set());
  }

  useLayoutEffect(() => {
    projectIdRef.current = projectId;
  }, [projectId]);

  const setQuery = useCallback(
    (query: Record<string, string>) => router.replace({ pathname, query }),
    [router, pathname],
  );

  const refreshProjects = useCallback(() => {
    listProjects()
      .then((d) => setProjects(d.projects || []))
      .catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((d) => { if (!cancelled) setProjects(d.projects || []); })
      .catch(() => { if (!cancelled) setProjects([]); });
    return () => { cancelled = true; };
  }, []);

  const loadTasks = useCallback(async () => {
    const requested = projectId;
    if (!requested) return;
    try {
      const [taskList, workers] = await Promise.all([listAgentTasks(requested), listWorkers(requested)]);
      if (projectIdRef.current !== requested) return;
      setTasks(taskList);
      setWorkerIds(new Set(workers.running));
    } catch {
      // daemon unreachable — leave state as is
    }
  }, [projectId]);

  const loadCost = useCallback(() => {
    const requested = projectId;
    if (!requested) return;
    getAgentCostSummary(requested)
      .then((summary) => {
        if (projectIdRef.current === requested) setCost(summary);
      })
      .catch(() => {
        if (projectIdRef.current === requested) setCost(null);
      });
  }, [projectId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadTasks();
    loadCost();
  }, [loadTasks, loadCost]);

  useEffect(() => {
    if (!projectId) return;
    return subscribe(`project:${projectId}`, (event) => {
      if (projectIdRef.current !== projectId) return;
      if (event.event === "task:created" || event.event === "task:updated") {
        const task = event.data as unknown as AgentTask;
        setTasks((prev) => {
          const i = prev.findIndex((x) => x.id === task.id);
          if (i === -1) return [task, ...prev];
          const next = [...prev];
          next[i] = task;
          return next;
        });
      } else if (event.event === "worker:started") {
        const tid = (event.data as { id: string }).id;
        setWorkerIds((prev) => new Set(prev).add(tid));
      } else if (event.event === "worker:exited") {
        const tid = (event.data as { id: string }).id;
        setWorkerIds((prev) => {
          const n = new Set(prev);
          n.delete(tid);
          return n;
        });
        loadCost();
      }
    });
  }, [projectId, subscribe, loadCost]);

  useEffect(() => {
    if (!projectId) return;
    return subscribe("task:suggestion", (event) => {
      const data = event.data as { project?: string };
      if (!data.project || data.project === projectId) loadCost();
    });
  }, [projectId, subscribe, loadCost]);

  async function handleImplement() {
    if (!projectId || !taskId) return;
    setBusy(true);
    try {
      const [preview, settings] = await Promise.all([
        previewImplement(projectId, taskId),
        getAgentSettings().catch(() => null),
      ]);
      const autonomyEnabled = settings?.selection_autonomy_enabled ?? true;
      if (preview.auto_decidable && autonomyEnabled) {
        try {
          await implementTask(projectId, taskId, { choice: "auto" });
          void loadTasks();
          return;
        } catch (e) {
          if (!(e instanceof ImplementConflictError)) throw e;
          setPicker({ preview: e.preview, notice: "blocked" });
          return;
        }
      }
      setPicker({ preview, notice: preview.auto_decidable ? "disabled" : null });
    } catch {
      // ignore
    } finally {
      setBusy(false);
    }
  }

  async function handleCancelRun() {
    if (!projectId || !taskId) return;
    setBusy(true);
    try {
      await stopWorker(projectId, taskId);
    } catch {
      // ignore — WS events re-sync liveness
    } finally {
      setBusy(false);
      void loadTasks();
    }
  }

  const project = useMemo(
    () => projects?.find((p) => p.project_id === projectId) ?? null,
    [projects, projectId],
  );
  const selectedTask = useMemo(
    () => (taskId ? tasks.find((x) => x.id === taskId) ?? null : null),
    [tasks, taskId],
  );
  const running = !!taskId && workerIds.has(taskId);
  const anyRunning = workerIds.size > 0;

  const shellClass = "flex flex-col flex-1 min-h-0 bg-zinc-950 text-zinc-100";

  if (!projectId) {
    return (
      <div className={shellClass}>
        <div className="flex-1 flex items-center justify-center p-6 overflow-y-auto">
          <div className="w-full max-w-md">
            <div className="flex items-center justify-between gap-3 mb-1">
              <h1 className="text-xl font-bold">{t("title")}</h1>
              <Button size="sm" onClick={() => setAddOpen(true)}>
                <Plus className="w-3.5 h-3.5 me-1" />
                {t("addProject")}
              </Button>
            </div>
            <p className="text-xs text-zinc-400 mb-4">{t("pickProjectHint")}</p>
            {projects === null ? (
              <p className="flex items-center gap-2 text-sm text-zinc-400">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("loading")}
              </p>
            ) : projects.length === 0 ? (
              <div className="rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-3 space-y-2">
                <p className="text-sm text-zinc-300">{t("noProjects")}</p>
                <p className="text-xs text-zinc-500">{t("noProjectsHint")}</p>
              </div>
            ) : (
              <ul className="space-y-2">
                {projects.map((p) => (
                  <li key={p.project_id}>
                    <button
                      type="button"
                      onClick={() => setQuery({ project: p.project_id })}
                      className="w-full text-start rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2.5 hover:border-zinc-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500"
                    >
                      <span className="block text-sm font-medium text-zinc-100">{p.project_name}</span>
                      <span className="block text-[11px] text-zinc-500 truncate mt-0.5">{p.project_path}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[10px] text-zinc-600 mt-6">{t("stackHint")}</p>
          </div>
        </div>
        <AddProjectModal
          open={addOpen}
          onClose={() => setAddOpen(false)}
          onCreated={() => { refreshProjects(); setAddOpen(false); }}
        />
      </div>
    );
  }

  return (
    <div className={shellClass}>
      <header className="shrink-0 border-b border-zinc-800 bg-zinc-950/80">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
          <div className="min-w-0 flex items-center gap-2">
            <h1 className="text-sm font-semibold text-zinc-100 shrink-0">{t("title")}</h1>
            <span className="text-zinc-700 select-none" aria-hidden>
              /
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-zinc-200 truncate max-w-[14rem] sm:max-w-[20rem]">
                {project?.project_name ?? projectId}
              </p>
              <button
                type="button"
                onClick={() => router.replace(pathname)}
                className="text-[11px] text-zinc-500 hover:text-zinc-300 underline-offset-2 hover:underline"
              >
                {t("changeProject")}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2 min-w-0">
            <label htmlFor="agent-app-task" className="text-[11px] text-zinc-500 shrink-0">
              {t("selectTask")}
            </label>
            <select
              id="agent-app-task"
              value={taskId ?? ""}
              onChange={(e) =>
                setQuery(e.target.value ? { project: projectId, task: e.target.value } : { project: projectId })
              }
              className="max-w-[min(100%,16rem)] bg-zinc-900 border border-zinc-700 rounded-md px-2 py-1.5 text-xs text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500"
            >
              <option value="">{t("projectChat")}</option>
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.title}
                  {workerIds.has(task.id) ? ` · ${t("runStatusRunning")}` : ""}
                </option>
              ))}
            </select>
            {selectedTask && (
              <span className="hidden sm:inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide bg-zinc-900 text-zinc-400 border border-zinc-800">
                {selectedTask.status}
              </span>
            )}
          </div>

          <div className="flex-1" />

          <div
            className="flex items-center gap-2 text-[11px] tabular-nums"
            aria-live="polite"
          >
            <span
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-medium ${
                running
                  ? "border-amber-700/60 bg-amber-950/40 text-amber-200"
                  : anyRunning
                    ? "border-zinc-700 bg-zinc-900 text-zinc-300"
                    : "border-zinc-800 bg-zinc-950 text-zinc-500"
              }`}
            >
              <span
                className={`size-1.5 rounded-full ${
                  running ? "bg-amber-400 animate-pulse" : anyRunning ? "bg-zinc-400" : "bg-zinc-600"
                }`}
                aria-hidden
              />
              {running
                ? t("runStatusRunning")
                : anyRunning
                  ? t("runStatusOther", { count: workerIds.size })
                  : t("runStatusIdle")}
            </span>
            {cost && cost.suggestion_count > 0 && (
              <span
                className="hidden md:inline text-zinc-500"
                title={t("costStripTitle")}
              >
                {t("costStrip", {
                  usd: formatUsd(cost.jev_cost_usd),
                  llm: cost.llm_total_tokens,
                })}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {taskId ? (
              <>
                <Button size="sm" variant="outline" onClick={() => void handleImplement()} disabled={busy || running}>
                  {busy && !running ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />}
                  <span className="ms-1">{t("implement")}</span>
                </Button>
                {running && (
                  <Button size="sm" variant="outline" onClick={() => void handleCancelRun()} disabled={busy}>
                    <Square className="w-3 h-3" />
                    <span className="ms-1">{t("cancelRun")}</span>
                  </Button>
                )}
              </>
            ) : (
              <p className="text-[11px] text-zinc-500 max-w-[14rem] leading-snug">{t("implementNeedsTask")}</p>
            )}
          </div>
        </div>
        {taskId && selectedTask && (
          <div className="px-4 pb-2 -mt-0.5">
            <p className="text-[11px] text-zinc-500 truncate">
              {t("contextTaskBound", { title: selectedTask.title })}
            </p>
          </div>
        )}
        {!taskId && (
          <div className="px-4 pb-2 -mt-0.5">
            <p className="text-[11px] text-zinc-500">{t("contextProjectChat")}</p>
          </div>
        )}
      </header>
      <div className="flex-1 min-h-0 p-3">
        <LoomAgentChat key={`${projectId}:${taskId ?? ""}`} projectId={projectId} taskId={taskId} />
      </div>
      {picker && taskId && (
        <ImplementPickerModal
          projectId={projectId}
          taskId={taskId}
          preview={picker.preview}
          notice={picker.notice}
          onClose={() => setPicker(null)}
          onImplemented={() => void loadTasks()}
        />
      )}
    </div>
  );
}
