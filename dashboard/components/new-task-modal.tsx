"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { createAgentTask, type AgentInfo, type AgentTask } from "@/lib/api";

const PRIORITY_MAP: Record<string, number> = { low: 0, medium: 1, high: 2 };

interface NewTaskModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  agents: AgentInfo[];
  tasks: AgentTask[];
  onCreated: () => void;
}

export function NewTaskModal({ open, onClose, projectId, agents, tasks, onCreated }: NewTaskModalProps) {
  const t = useTranslations("NewTaskModal");
  const tPriority = useTranslations("Common.priority");
  const ref = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [instruction, setInstruction] = useState("");
  const [assignee, setAssignee] = useState(""); // "" = Auto
  const [priority, setPriority] = useState("medium");
  const [deps, setDeps] = useState<string[]>([]);
  const [criteria, setCriteria] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    else if (!open && d.open) d.close();
  }, [open]);

  function resolveAssignee(): string | null {
    if (assignee) return assignee;
    const online = agents.find((a) => a.status === "online");
    return online ? online.agent_id : null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !instruction.trim()) return;
    setLoading(true); setError("");
    try {
      await createAgentTask(projectId, {
        title, instruction,
        assignee: resolveAssignee(),
        priority: PRIORITY_MAP[priority],
        dependencies: deps,
        acceptance_criteria: criteria,
      });
      onCreated(); onClose();
      setTitle(""); setInstruction(""); setDeps([]); setCriteria("");
    } catch {
      setError(t("error"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={() => { if (open) onClose(); }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      className="fixed inset-0 m-auto h-fit w-fit rounded-xl p-0 bg-transparent max-w-none"
    >
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[520px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">{t("heading")}</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("title")}</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
              required
            />
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("instruction")}</label>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder={t("instructionPlaceholder")}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-24 resize-none"
              required
            />
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("assignee")}</label>
            <select
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
            >
              <option value="">{t("autoAssign")}</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("priority")}</label>
            <div className="flex gap-2">
              {(["low", "medium", "high"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                    priority === p
                      ? "border-amber-700 bg-amber-900/30 text-amber-300"
                      : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {tPriority(p)}
                </button>
              ))}
            </div>
          </div>
          {tasks.length > 0 && (
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">{t("dependencies")}</label>
              <select
                multiple
                value={deps}
                onChange={(e) => setDeps(Array.from(e.target.selectedOptions, (o) => o.value))}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-20"
              >
                {tasks.map((task) => (
                  <option key={task.id} value={task.id}>{task.title}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("acceptanceCriteria")}</label>
            <textarea
              value={criteria}
              onChange={(e) => setCriteria(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-16 resize-none"
            />
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={loading} className="flex-1">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              <span className="ms-2">{t("create")}</span>
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>{t("cancel")}</Button>
          </div>
        </form>
      </div>
    </dialog>
  );
}
