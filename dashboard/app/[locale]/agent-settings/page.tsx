"use client";

import { useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { AgentSettingsPanel } from "@/components/agent-settings-panel";

export default function AgentSettingsPage() {
  const t = useTranslations("AgentSettingsPage");

  return (
    <div className="flex flex-col flex-1 min-h-0 max-w-3xl mx-auto w-full">
      <div className="flex items-center gap-3 px-1 py-3 shrink-0">
        <Link
          href="/agent-app"
          className="inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-[0.8rem] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          {t("back")}
        </Link>
        <div>
          <h1 className="text-lg font-bold text-zinc-100">{t("title")}</h1>
          <p className="text-xs text-zinc-500">{t("subtitle")}</p>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 mb-6">
        <AgentSettingsPanel />
      </div>
    </div>
  );
}
