"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  implementTask,
  ImplementConflictError,
  isSelectionPreview,
  type FitLevel,
  type ImplementRequest,
  type RankedStrategy,
  type SelectionPreview,
} from "@/lib/api";

export type ImplementPickerNotice = "blocked" | "disabled" | null;

interface ImplementPickerModalProps {
  projectId: string;
  taskId: string;
  preview: SelectionPreview;
  notice?: ImplementPickerNotice;
  onClose: () => void;
  onImplemented: () => void;
}

const FIT_STYLE: Record<FitLevel, string> = {
  High: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  Medium: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  Low: "bg-zinc-800 text-zinc-400 border-zinc-700",
};

const FIT_KEY: Record<FitLevel, "high" | "medium" | "low"> = {
  High: "high",
  Medium: "medium",
  Low: "low",
};

const COST_KEY: Record<string, "low" | "med" | "high"> = {
  Low: "low",
  Med: "med",
  High: "high",
};

const SELECTION_FALLBACK_WHY = "selection_fallback";

export function ImplementPickerModal(props: ImplementPickerModalProps) {
  const { projectId, taskId, preview: initialPreview, notice: initialNotice = null, onClose, onImplemented } = props;
  const t = useTranslations("ImplementPicker");
  const ref = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<SelectionPreview>(initialPreview);
  const [notice, setNotice] = useState<ImplementPickerNotice>(initialNotice);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Native dialog gives Escape handling, focus trapping and a ::backdrop.
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  async function submit(body: ImplementRequest) {
    setBusy(true);
    setError("");
    try {
      await implementTask(projectId, taskId, body);
      onImplemented();
      onClose();
    } catch (e) {
      if (e instanceof ImplementConflictError && isSelectionPreview(e.preview)) {
        setPreview(e.preview);
        setNotice("blocked");
      } else {
        setError(t("error"));
      }
    } finally {
      setBusy(false);
    }
  }

  function handlePick(strategy: RankedStrategy) {
    void submit({ choice: "user", family_id: strategy.family_id, modifier_ids: strategy.modifier_ids, recommended_family_id: preview.recommended?.family_id });
  }

  function handleAuto() {
    void submit({ choice: "delegate" });
  }

  function whyText(line: string): string {
    return line === SELECTION_FALLBACK_WHY ? t("selectionFallback") : line;
  }

  function costLabel(band: string | null): string {
    const key = band ? COST_KEY[band] : undefined;
    return key ? t(`costBand.${key}`) : t("costUnknown");
  }

  const candidates = isSelectionPreview(preview) ? preview.top3 : [];

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
      className="fixed inset-0 m-auto h-fit w-fit rounded-xl p-0 bg-transparent max-w-none"
    >
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[560px] max-w-[95vw] p-6">
        <h2 className="text-lg font-bold text-zinc-100">{t("title")}</h2>
        <p className="text-xs text-zinc-400 mt-1 mb-4">{t("subtitle")}</p>

        {notice === "blocked" && (
          <p className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-300">
            {t("autonomyBlocked")}
          </p>
        )}
        {notice === "disabled" && (
          <p className="mb-3 rounded-md border border-zinc-700 bg-zinc-800/40 p-2 text-xs text-zinc-300">
            {t("autonomyDisabled")}
          </p>
        )}
        {preview.fallback && (
          <p className="mb-3 rounded-md border border-zinc-700 bg-zinc-800/40 p-2 text-xs text-zinc-300">
            {t("fallbackNotice")}
          </p>
        )}

        <div className="space-y-3 max-h-[55vh] overflow-y-auto">
          {candidates.length === 0 && <p className="text-xs text-zinc-500">{t("noCandidates")}</p>}
          {candidates.map((c) => (
            <div key={`${c.family_id}:${c.modifier_ids.join(",")}`} className="rounded-lg border border-zinc-700 bg-zinc-950/60 p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-zinc-100">{c.name}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] ${FIT_STYLE[c.fit] ?? FIT_STYLE.Low}`}>
                      {t(`fit.${FIT_KEY[c.fit] ?? "low"}`)}
                    </span>
                    <span className="text-[11px] text-zinc-400">{t("cost", { band: costLabel(c.expected_cost_class) })}</span>
                  </div>
                </div>
                <Button size="sm" onClick={() => handlePick(c)} disabled={busy}>
                  {t("pick")}
                </Button>
              </div>
              {c.why.length > 0 && (
                <div className="mt-2">
                  <p className="text-[10px] uppercase tracking-wide text-zinc-500">{t("why")}</p>
                  <ul className="mt-1 list-disc ps-4 space-y-0.5 text-xs text-zinc-300">
                    {c.why.map((w, i) => (
                      <li key={i}>{whyText(w)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>

        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}

        <div className="mt-4 flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>
            {t("cancel")}
          </Button>
          <Button size="sm" variant="secondary" onClick={handleAuto} disabled={busy}>
            {busy ? <Loader2 className="w-3.5 h-3.5 me-1 animate-spin" /> : <Sparkles className="w-3.5 h-3.5 me-1" />}
            {t("letAgentDecide")}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
