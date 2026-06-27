"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { X, GitMerge, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  getTaskDiff,
  mergeTask,
  updateAgentTask,
  type AgentTask,
  type AgentInfo,
  type AgentTaskStatus,
} from "@/lib/api";

const STATUSES: AgentTaskStatus[] = [
  "triage",
  "todo",
  "ready",
  "running",
  "blocked",
  "done",
  "archived",
];

interface TaskDetailDrawerProps {
  task: AgentTask | null;
  projectId: string;
  agents: AgentInfo[];
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

export function TaskDetailDrawer({
  task,
  projectId,
  agents,
  onClose,
  onChanged,
}: TaskDetailDrawerProps) {
  const t = useTranslations("TaskDetail");
  const [diff, setDiff] = useState("");
  const [merging, setMerging] = useState(false);
  const [mergeMsg, setMergeMsg] = useState("");

  useEffect(() => {
    if (!task) return;
    if (task.status === "done" || task.status === "blocked") {
      let cancelled = false;
      getTaskDiff(projectId, task.id)
        .then((d) => {
          if (!cancelled) setDiff(d.diff);
        })
        .catch(() => {});
      return () => {
        cancelled = true;
      };
    }
  }, [task, projectId]);

  if (!task) return null;

  async function handleMerge() {
    setMerging(true);
    setMergeMsg("");
    try {
      const res = await mergeTask(projectId, task!.id);
      setMergeMsg(res.merged ? t("mergeOk") : t("mergeConflict"));
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
      // ignore — the finally re-syncs from server state
    } finally {
      onChanged();
    }
  }

  return (
    <div className="fixed inset-y-0 end-0 w-[420px] bg-zinc-950 border-s border-zinc-800 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-zinc-800">
        <h3 className="text-sm font-bold text-zinc-100 truncate">{task.title}</h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        <div>
          <label htmlFor="task-status" className="text-zinc-500 block mb-1">{t("status")}</label>
          <select
            id="task-status"
            value={task.status}
            onChange={(e) => handleStatus(e.target.value as AgentTaskStatus)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
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
              <option key={a.agent_id} value={a.agent_id}>
                {a.agent_name}
              </option>
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
        {task.result && (
          <div>
            <label className="text-zinc-500 block mb-1">{t("result")}</label>
            <p className="text-zinc-300 whitespace-pre-wrap">{parseSummary(task.result)}</p>
          </div>
        )}
        {(task.status === "done" || task.status === "blocked") && diff && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-zinc-500">{t("diff")}</label>
              <Button size="sm" variant="outline" onClick={handleMerge} disabled={merging}>
                {merging ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <GitMerge className="w-3 h-3" />
                )}
                <span className="ms-1">{t("merge")}</span>
              </Button>
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
