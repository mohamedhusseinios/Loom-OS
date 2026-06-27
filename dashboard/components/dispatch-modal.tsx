"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("DispatchModal");
  const tPriority = useTranslations("Common.priority");
  const ref = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState("");
  const [instruction, setInstruction] = useState("");
  const [priority, setPriority] = useState("medium");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Drive the native dialog. showModal()/close() give us Escape handling,
  // focus trapping, and the ::backdrop overlay for free.
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  // Sync parent state when the dialog is dismissed natively (Escape). The
  // `close` event fires after any close; we only need to notify React if the
  // `open` prop hasn't already flipped to false (i.e. it wasn't our doing).
  const onNativeClose = () => {
    if (open) onClose();
  };

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
      setError(t("error"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onNativeClose}
      // Backdrop click: the click lands on the <dialog> element itself (not a
      // child), since the panel fills the dialog's content area.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 m-auto h-fit w-fit rounded-xl p-0 bg-transparent max-w-none"
    >
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[480px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">{t("heading")}</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("targetAgent")}</label>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
              required
            >
              <option value="">{t("selectAgent")}</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_name}>
                  {a.agent_name}
                </option>
              ))}
            </select>
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
            <label className="text-xs text-zinc-400 mb-1 block">{t("priority")}</label>
            <div className="flex gap-2">
              {(["low", "medium", "high"] as const).map((p) => (
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
                  {tPriority(p)}
                </button>
              ))}
            </div>
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={loading} className="flex-1">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              <span className="ms-2">{t("dispatch")}</span>
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      </div>
    </dialog>
  );
}
