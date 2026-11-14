"use client";

import { useTranslations } from "next-intl";
import { Check, X, Sparkles, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { TaskSuggestion } from "@/lib/api";

interface SuggestionChipProps {
  suggestion: TaskSuggestion | null;
  busy?: boolean;
  onAccept: () => void;
  onDismiss: () => void;
  onSuggest?: () => void;
  onImplement?: () => void;
}

export function SuggestionChip({
  suggestion,
  busy,
  onAccept,
  onDismiss,
  onSuggest,
  onImplement,
}: SuggestionChipProps) {
  const t = useTranslations("LoomAgent");

  if (!suggestion || suggestion.status !== "pending") {
    return onSuggest ? (
      <Button size="sm" variant="outline" onClick={onSuggest} disabled={busy}>
        {busy ? <Loader2 className="w-3.5 h-3.5 me-1 animate-spin" /> : <Sparkles className="w-3.5 h-3.5 me-1" />}
        {t("suggestNext")}
      </Button>
    ) : null;
  }

  const pct = Math.round((suggestion.confidence || 0) * 100);

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/80 p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-zinc-500">{t("suggestion")}</p>
          <p className="text-sm font-medium text-zinc-100">{suggestion.action_label}</p>
          <p className="text-xs text-zinc-400 mt-1 whitespace-pre-wrap">{suggestion.prose}</p>
          <p className="text-[11px] text-zinc-500 mt-1">
            {t("confidence", { pct })}
            {suggestion.jev_skipped ? ` · ${t("jevSkipped")}` : ""}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={onAccept} disabled={busy}>
          <Check className="w-3.5 h-3.5 me-1" /> {t("accept")}
        </Button>
        <Button size="sm" variant="outline" onClick={onDismiss} disabled={busy}>
          <X className="w-3.5 h-3.5 me-1" /> {t("dismiss")}
        </Button>
        {onImplement && (
          <Button size="sm" variant="secondary" onClick={onImplement} disabled={busy}>
            {t("implement")}
          </Button>
        )}
        {onSuggest && (
          <Button size="sm" variant="ghost" onClick={onSuggest} disabled={busy}>
            <Sparkles className="w-3.5 h-3.5 me-1" /> {t("refresh")}
          </Button>
        )}
      </div>
    </div>
  );
}
