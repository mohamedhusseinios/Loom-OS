"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { GripVertical } from "lucide-react";
import type { AgentTask, AgentTaskStatus } from "@/lib/api";

const COLUMNS: { status: AgentTaskStatus; key: string; color: string }[] = [
  { status: "todo", key: "todo", color: "text-zinc-400" },
  { status: "ready", key: "ready", color: "text-blue-400" },
  { status: "running", key: "running", color: "text-amber-400" },
  { status: "blocked", key: "blocked", color: "text-red-400" },
  { status: "done", key: "done", color: "text-emerald-400" },
];

interface TaskBoardProps {
  tasks: AgentTask[];
  onMove: (taskId: string, status: AgentTaskStatus) => void;
  onSelect: (task: AgentTask) => void;
}

export function TaskBoard({ tasks, onMove, onSelect }: TaskBoardProps) {
  const t = useTranslations("TaskBoard");
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<AgentTaskStatus | null>(null);

  return (
    <div className="grid grid-cols-5 gap-3 flex-1 min-h-0">
      {COLUMNS.map((col) => {
        const colTasks = tasks.filter((x) => x.status === col.status);
        return (
          <div
            key={col.status}
            onDragOver={(e) => { e.preventDefault(); setOverCol(col.status); }}
            onDragLeave={() => setOverCol((c) => (c === col.status ? null : c))}
            onDrop={(e) => {
              e.preventDefault();
              if (dragId) onMove(dragId, col.status);
              setDragId(null); setOverCol(null);
            }}
            className={`flex flex-col rounded-lg border p-2 overflow-y-auto transition-colors ${
              overCol === col.status ? "border-zinc-600 bg-zinc-900/60" : "border-zinc-800 bg-zinc-950"
            }`}
          >
            <div className="flex items-center gap-2 mb-2 px-1">
              <span className={`text-xs font-semibold ${col.color}`}>{t(`columns.${col.key}`)}</span>
              <span className="text-xs text-zinc-600">{colTasks.length}</span>
            </div>
            <div className="space-y-2">
              {colTasks.map((task) => (
                <div
                  key={task.id}
                  draggable
                  onDragStart={() => setDragId(task.id)}
                  onDragEnd={() => { setDragId(null); setOverCol(null); }}
                  onClick={() => onSelect(task)}
                  className="group cursor-pointer rounded-md border border-zinc-800 bg-zinc-900 p-2 hover:border-zinc-700"
                >
                  <div className="flex items-start gap-1">
                    <GripVertical className="w-3 h-3 mt-0.5 text-zinc-700 group-hover:text-zinc-500 shrink-0" />
                    <p className="text-xs font-medium text-zinc-200 line-clamp-2">{task.title}</p>
                  </div>
                  <div className="flex items-center gap-2 mt-1 ps-4">
                    {task.assignee && <span className="text-[10px] text-zinc-500 truncate">{task.assignee}</span>}
                    {task.priority > 0 && <span className="text-[10px] text-amber-500">P{task.priority}</span>}
                    {task.dependencies.length > 0 && (
                      <span className="text-[10px] text-zinc-600">⛓ {task.dependencies.length}</span>
                    )}
                  </div>
                </div>
              ))}
              {colTasks.length === 0 && (
                <p className="text-[10px] text-zinc-700 px-1 py-2">{t("emptyColumn")}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
