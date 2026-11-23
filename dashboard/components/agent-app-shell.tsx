"use client";

import { useCallback, useEffect, useState } from "react";
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
  ImplementConflictError,
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
  const [picker, setPicker] = useState<{ preview: SelectionPreview; notice: ImplementPickerNotice } | null>(null);

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
    if (projectId) return;
    let cancelled = false;
    listProjects()
      .then((d) => { if (!cancelled) setProjects(d.projects || []); })
      .catch(() => { if (!cancelled) setProjects([]); });
    return () => { cancelled = true; };
  }, [projectId]);

  const loadTasks = useCallback(async () => {
    if (!projectId) return;
    try {
      const [taskList, workers] = await Promise.all([listAgentTasks(projectId), listWorkers(projectId)]);
      setTasks(taskList);
      setWorkerIds(new Set(workers.running));
    } catch {
      // daemon unreachable — leave state as is
    }
  }, [projectId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    if (!projectId) return;
    return subscribe(`project:${projectId}`, (event) => {
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
      }
    });
  }, [projectId, subscribe]);

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
            <p className="text-xs text-zinc-500 mb-4">{t("pickProject")}</p>
            {projects === null ? (
              <p className="flex items-center gap-2 text-sm text-zinc-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("loading")}
              </p>
            ) : projects.length === 0 ? (
              <p className="text-sm text-zinc-500 mb-4">{t("noProjects")}</p>
            ) : (
              <ul className="space-y-2">
                {projects.map((p) => (
                  <li key={p.project_id}>
                    <button
                      type="button"
                      onClick={() => setQuery({ project: p.project_id })}
                      className="w-full text-start rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 hover:border-zinc-600"
                    >
                      <span className="block text-sm font-medium text-zinc-100">{p.project_name}</span>
                      <span className="block text-[11px] text-zinc-500 truncate">{p.project_path}</span>
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

  const running = !!taskId && workerIds.has(taskId);

  return (
    <div className={shellClass}>
      <header className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        <h1 className="text-sm font-bold me-2">{t("title")}</h1>
        <button
          type="button"
          onClick={() => router.replace(pathname)}
          className="text-[11px] text-zinc-500 hover:text-zinc-300 underline"
        >
          {t("changeProject")}
        </button>
        <span className="text-[11px] text-zinc-600 truncate">{projectId}</span>
        <div className="flex-1" />
        <label htmlFor="agent-app-task" className="text-[11px] text-zinc-500">{t("selectTask")}</label>
        <select
          id="agent-app-task"
          value={taskId ?? ""}
          onChange={(e) =>
            setQuery(e.target.value ? { project: projectId, task: e.target.value } : { project: projectId })
          }
          className="max-w-[260px] bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1 text-xs text-zinc-200"
        >
          <option value="">{t("projectChat")}</option>
          {tasks.map((task) => (
            <option key={task.id} value={task.id}>{task.title}</option>
          ))}
        </select>
        {taskId && (
          <Button size="sm" variant="outline" onClick={() => void handleImplement()} disabled={busy || running}>
            {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />}
            <span className="ms-1">{t("implement")}</span>
          </Button>
        )}
        {running && (
          <Button size="sm" variant="outline" onClick={() => void handleCancelRun()} disabled={busy}>
            <Square className="w-3 h-3" />
            <span className="ms-1">{t("cancelRun")}</span>
          </Button>
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
