"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  listAgentTasks, getProject, updateAgentTask,
  type AgentTask, type AgentTaskStatus, type AgentInfo,
} from "@/lib/api";
import { useWebSocket } from "@/lib/use-websocket";
import { TaskBoard } from "@/components/task-board";
import { NewTaskModal } from "@/components/new-task-modal";
import { TaskDetailDrawer } from "@/components/task-detail-drawer";

export default function TasksPage() {
  const t = useTranslations("TaskBoard");
  const { id } = useParams<{ id: string }>();
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  // Starts true — no synchronous setLoading(true) call inside any effect.
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [selected, setSelected] = useState<AgentTask | null>(null);
  const { subscribe } = useWebSocket();

  // Stable callback for child props (onCreated / onChanged / retry after failed move).
  // Not called from within an effect body — only passed as prop or invoked from
  // event handlers — so it does not trigger react-hooks/set-state-in-effect.
  const loadData = useCallback(async () => {
    try {
      const [taskList, project] = await Promise.all([listAgentTasks(id), getProject(id)]);
      setTasks(taskList);
      setAgents(project.agents || []);
    } catch {
      // no tasks yet
    } finally {
      setLoading(false);
    }
  }, [id]);

  // Initial load uses an inline async IIFE so the setState calls happen after
  // awaits, never synchronously in the effect body.  This satisfies the
  // react-hooks/set-state-in-effect rule (the rule traces into named functions
  // called from effect bodies, but not into inline async IIFEs).
  useEffect(() => {
    (async () => {
      try {
        const [taskList, project] = await Promise.all([listAgentTasks(id), getProject(id)]);
        setTasks(taskList);
        setAgents(project.agents || []);
      } catch {
        // no tasks yet
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  // Live WebSocket updates — setState is inside the subscribe callback, not
  // the effect body itself, so no set-state-in-effect violation.
  useEffect(() => {
    const upsert = (task: AgentTask) =>
      setTasks((prev) => {
        const i = prev.findIndex((x) => x.id === task.id);
        if (i === -1) return [task, ...prev];
        const next = [...prev]; next[i] = task; return next;
      });
    return subscribe(`project:${id}`, (event) => {
      if (event.event === "task:created" || event.event === "task:updated") {
        upsert(event.data as unknown as AgentTask);
      }
    });
  }, [id, subscribe]);

  async function handleMove(taskId: string, status: AgentTaskStatus) {
    // Optimistic update.
    setTasks((prev) => prev.map((x) => (x.id === taskId ? { ...x, status } : x)));
    try {
      const updated = await updateAgentTask(id, taskId, { status });
      setTasks((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    } catch {
      void loadData();
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-96 text-zinc-500">{t("loading")}</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-xl font-bold">{t("heading")}</h2>
          <p className="text-xs text-zinc-500">{t("count", { count: tasks.length })}</p>
        </div>
        <Button size="sm" onClick={() => setModalOpen(true)}>
          <Plus className="w-3.5 h-3.5 me-1" />
          {t("newTask")}
        </Button>
      </div>

      <TaskBoard tasks={tasks} onMove={handleMove} onSelect={setSelected} />

      <NewTaskModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={id}
        agents={agents}
        tasks={tasks}
        onCreated={loadData}
      />

      {/* key remounts the drawer when the selected task changes, resetting its
          internal diff/edit state (C5 drawer-remount contract). */}
      <TaskDetailDrawer
        key={selected?.id ?? "none"}
        task={selected}
        projectId={id}
        agents={agents}
        onClose={() => setSelected(null)}
        onChanged={loadData}
      />
    </div>
  );
}
