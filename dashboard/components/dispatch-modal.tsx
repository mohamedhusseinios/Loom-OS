"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { dispatchTask } from "@/lib/api";
import { Loader2, Send } from "lucide-react";

interface DispatchModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  agents: { agent_name: string; agent_id: string }[];
  onDispatched: () => void;
}

export function DispatchModal({ open, onClose, projectId, agents, onDispatched }: DispatchModalProps) {
  const [target, setTarget] = useState("");
  const [instruction, setInstruction] = useState("");
  const [priority, setPriority] = useState("medium");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!target || !instruction.trim()) return;
    setLoading(true);
    setError("");
    try {
      await dispatchTask(projectId, { target_agent: target, instruction, priority });
      onDispatched();
      onClose();
      setInstruction("");
    } catch {
      setError("Failed to dispatch task");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[480px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">Dispatch Task</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">Target Agent</label>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
              required
            >
              <option value="">Select agent...</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_name}>
                  {a.agent_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-zinc-400 mb-1 block">Instruction</label>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="e.g. Review the auth module for security issues"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-24 resize-none"
              required
            />
          </div>

          <div>
            <label className="text-xs text-zinc-400 mb-1 block">Priority</label>
            <div className="flex gap-2">
              {["low", "medium", "high"].map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                    priority === p
                      ? p === "high"
                        ? "border-red-700 bg-red-900/30 text-red-300"
                        : p === "medium"
                        ? "border-amber-700 bg-amber-900/30 text-amber-300"
                        : "border-zinc-600 bg-zinc-800 text-zinc-400"
                      : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={loading} className="flex-1">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              <span className="ml-2">Dispatch</span>
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
