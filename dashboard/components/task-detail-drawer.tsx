"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { X, GitMerge, Loader2, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWebSocket } from "@/lib/use-websocket";
import {
  getTaskDiff,
  mergeTask,
  getBranches,
  updateAgentTask,
  getTaskProgress,
  startWorker,
  stopWorker,
  type AgentTask,
  type AgentInfo,
  type AgentTaskStatus,
  type TaskProgressItem,
} from "@/lib/api";

const STATUSES: AgentTaskStatus[] = [
  "triage", "todo", "ready", "running", "blocked", "done", "archived",
];

interface TaskDetailDrawerProps {
  task: AgentTask | null;
  projectId: string;
  agents: AgentInfo[];
  workerRunning: boolean;
  assigneeRunnable: boolean;
  onClose: () => void;
  onChanged: () => void;
}

function parseSummary(result: string | null): string {
  if (!result) return "";
  try {
    const parsed = JSON.parse(result);
    return parsed.summary || parsed.error || result;
  } catch {
    return result;
  }
}

const KIND_STYLE: Record<string, string> = {
  milestone: "text-sky-400",
  tool: "text-violet-300",
  text: "text-zinc-300",
  error: "text-red-400",
  summary: "text-emerald-300",
};

export function TaskDetailDrawer({
  task,
  projectId,
  agents,
  workerRunning,
  assigneeRunnable,
  onClose,
  onChanged,
}: TaskDetailDrawerProps) {
  const t = useTranslations("TaskDetail");
  const { subscribe } = useWebSocket();
  const [diff, setDiff] = useState("");
  const [merging, setMerging] = useState(false);
  const [mergeMsg, setMergeMsg] = useState("");
  const [branches, setBranches] = useState<{ name: string; remote: boolean }[]>([]);
  const [target, setTarget] = useState("");
  const [progress, setProgress] = useState<TaskProgressItem[]>([]);
  const [busy, setBusy] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  // Load diff for completed/blocked tasks.
  useEffect(() => {
    if (!task) return;
    if (task.status === "done" || task.status === "blocked") {
      let cancelled = false;
      getTaskDiff(projectId, task.id)
        .then((d) => { if (!cancelled) setDiff(d.diff); })
        .catch(() => {});
      return () => { cancelled = true; };
    }
  }, [task, projectId]);

  // Load branch list + default target for completed/blocked tasks.
  useEffect(() => {
    if (!task) return;
    if (task.status === "done" || task.status === "blocked") {
      let cancelled = false;
      getBranches(projectId)
        .then((b) => {
          if (cancelled) return;
          setBranches(b.branches);
          setTarget(b.current);
        })
        .catch(() => {});
      return () => { cancelled = true; };
    }
  }, [task, projectId]);

  // Load progress history once, then append live events (deduped by seq).
  useEffect(() => {
    if (!task) return;
    const taskId = task.id;
    let cancelled = false;
    getTaskProgress(projectId, taskId)
      .then((p) => {
        if (cancelled) return;
        setProgress((live) =>
          live.length === 0
            ? p.items
            : [...p.items, ...live.filter((l) => !p.items.some((h) => h.seq === l.seq))],
        );
      })
      .catch(() => {});
    const unsub = subscribe("task:progress", (event) => {
      const d = event.data as { id: string; seq: number; kind: string; message: string };
      if (d.id !== taskId) return;
      setProgress((prev) =>
        prev.some((i) => i.seq === d.seq)
          ? prev
          : [...prev, { task_id: taskId, seq: d.seq, kind: d.kind, message: d.message, ts: "" }],
      );
    });
    return () => { cancelled = true; unsub(); };
  }, [task, projectId, subscribe]);

  // Auto-scroll the feed to the newest line.
  useEffect(() => {
    if (feedRef.current && progress.length > 0) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [progress]);

  if (!task) return null;

  async function handleMerge() {
    setMerging(true);
    setMergeMsg("");
    try {
      const sel = branches.find((b) => b.name === target);
      const res = await mergeTask(projectId, task!.id, target, sel?.remote ?? false);
      setMergeMsg(res.merged ? t("mergedInto", { branch: res.target }) : t("mergeConflict"));
      if (res.merged) onChanged();
    } catch {
      setMergeMsg(t("mergeConflict"));
    } finally {
      setMerging(false);
    }
  }

  async function handleStatus(status: AgentTaskStatus) {
    try {
      await updateAgentTask(projectId, task!.id, { status });
    } catch {
      // ignore — the finally re-syncs from server state
    } finally {
      onChanged();
    }
  }

  async function handleAssignee(assignee: string) {
    try {
      await updateAgentTask(projectId, task!.id, { assignee: assignee || null });
    } catch {
      // ignore
    } finally {
      onChanged();
    }
  }

  async function handleRun() {
    setBusy(true);
    try {
      await startWorker(projectId, task!.id);
    } catch {
      // ignore — WS events re-sync liveness
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  async function handleStop() {
    setBusy(true);
    try {
      await stopWorker(projectId, task!.id);
    } catch {
      // ignore
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  const isDone = task.status === "done";
  const isBlocked = task.status === "blocked";
  const assigneeShort = task.assignee
    ? agents.find((a) => a.agent_id === task.assignee)?.agent_name ?? task.assignee
    : "";
  const isExternal = !!task.assignee && !assigneeRunnable;
  const showNoWorker = task.status === "running" && !workerRunning && !isExternal;
  const showExternal = task.status === "running" && !workerRunning && isExternal;
  const canRun = !workerRunning && !isDone && !!task.assignee && assigneeRunnable;

  return (
    <div className="fixed inset-y-0 end-0 w-[440px] bg-zinc-950 border-s border-zinc-800 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-zinc-800">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-bold text-zinc-100 truncate">{task.title}</h3>
          <span
            className={`shrink-0 inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${
              workerRunning ? "bg-amber-500/10 text-amber-400" : "bg-zinc-800 text-zinc-500"
            }`}
          >
            {workerRunning && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
            {workerRunning ? t("workerRunning") : t("workerIdle")}
          </span>
        </div>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        {workerRunning ? (
          <Button size="sm" variant="outline" onClick={handleStop} disabled={busy}>
            <Square className="w-3 h-3" />
            <span className="ms-1">{t("stop")}</span>
          </Button>
        ) : (
          <Button size="sm" onClick={handleRun} disabled={busy || !canRun}>
            <Play className="w-3 h-3" />
            <span className="ms-1">{t("run")}</span>
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {showNoWorker && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2">
            <p className="text-amber-300 font-medium">{t("noWorkerTitle")}</p>
            <p className="text-amber-200/80 mt-1">{t("noWorkerBody")}</p>
          </div>
        )}
        {showExternal && (
          <div className="rounded-md border border-zinc-700 bg-zinc-800/40 p-2">
            <p className="text-zinc-300 font-medium">{t("externalAgentTitle")}</p>
            <p className="text-zinc-400 mt-1">{t("externalAgentBody", { agent: assigneeShort })}</p>
          </div>
        )}

        <div>
          <label htmlFor="task-status" className="text-zinc-500 block mb-1">{t("status")}</label>
          <select
            id="task-status"
            value={task.status}
            onChange={(e) => handleStatus(e.target.value as AgentTaskStatus)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div>
          <label htmlFor="task-assignee" className="text-zinc-500 block mb-1">{t("assignee")}</label>
          <select
            id="task-assignee"
            value={task.assignee || ""}
            onChange={(e) => handleAssignee(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            <option value="">{t("unassigned")}</option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-zinc-500 block mb-1">{t("instruction")}</label>
          <p className="text-zinc-300 whitespace-pre-wrap">{task.instruction}</p>
        </div>

        {task.acceptance_criteria && (
          <div>
            <label className="text-zinc-500 block mb-1">{t("acceptanceCriteria")}</label>
            <p className="text-zinc-300 whitespace-pre-wrap">{task.acceptance_criteria}</p>
          </div>
        )}

        <div>
          <label className="text-zinc-500 block mb-1">{t("activity")}</label>
          <div
            ref={feedRef}
            className="bg-black/40 border border-zinc-800 rounded p-2 max-h-72 overflow-y-auto space-y-1"
          >
            {progress.length === 0 && (
              <p className="text-[10px] text-zinc-600">{t("noActivity")}</p>
            )}
            {progress.map((item) => (
              <div key={item.seq} className="flex gap-2">
                <span className="text-[9px] text-zinc-700 mt-0.5 shrink-0 w-6 text-end">{item.seq}</span>
                <span className={`text-[11px] whitespace-pre-wrap ${KIND_STYLE[item.kind] || "text-zinc-300"}`}>
                  {item.message}
                </span>
              </div>
            ))}
          </div>
        </div>

        {task.result && (
          <div>
            <label className="text-zinc-500 block mb-1">{t("result")}</label>
            <p className="text-zinc-300 whitespace-pre-wrap">{parseSummary(task.result)}</p>
          </div>
        )}

        {(isDone || isBlocked) && diff && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-zinc-500">{t("diff")}</label>
              <div className="flex items-center gap-1">
                <select
                  aria-label={t("mergeInto")}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  disabled={merging}
                  className="bg-zinc-900 border border-zinc-700 rounded text-[11px] text-zinc-200 px-1 py-0.5 max-w-[160px]"
                >
                  {branches.map((b) => (
                    <option key={b.name} value={b.name}>{b.name}</option>
                  ))}
                </select>
                <Button size="sm" variant="outline" onClick={handleMerge} disabled={merging || !target}>
                  {merging ? <Loader2 className="w-3 h-3 animate-spin" /> : <GitMerge className="w-3 h-3" />}
                  <span className="ms-1">{t("merge")}</span>
                </Button>
              </div>
            </div>
            {mergeMsg && <p className="text-[10px] text-zinc-400 mb-1">{mergeMsg}</p>}
            <pre className="bg-black/50 border border-zinc-800 rounded p-2 text-[10px] text-zinc-300 overflow-x-auto max-h-64">
              {diff}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
