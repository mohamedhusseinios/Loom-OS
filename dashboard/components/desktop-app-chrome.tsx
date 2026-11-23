"use client";

import { useTranslations } from "next-intl";
import { Settings } from "lucide-react";
import { Link, usePathname } from "@/i18n/navigation";

/**
 * Persistent Agent | Dashboard switcher for the desktop app window.
 * Navigation stays in the same WebView — never opens the system browser.
 */
export function DesktopAppChrome() {
  const t = useTranslations("AgentApp");
  const pathname = usePathname();
  const onAgent = pathname.startsWith("/agent-app") || pathname.startsWith("/agent-settings");
  const active: "agent" | "dashboard" = onAgent ? "agent" : "dashboard";

  const tabClass = (id: "agent" | "dashboard") =>
    `px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
      active === id
        ? "bg-zinc-800 text-zinc-100 border-zinc-600"
        : "bg-transparent text-zinc-400 border-transparent hover:text-zinc-200 hover:bg-zinc-900"
    }`;

  return (
    <header className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-950 shrink-0">
      <span className="text-sm font-semibold text-zinc-100 tracking-tight">Loom Coding Agent</span>
      <nav className="flex items-center gap-1" role="tablist" aria-label="App sections">
        <Link href="/agent-app" role="tab" aria-selected={active === "agent"} className={tabClass("agent")}>
          {t("tabAgent")}
        </Link>
        <Link href="/" role="tab" aria-selected={active === "dashboard"} className={tabClass("dashboard")}>
          {t("tabDashboard")}
        </Link>
      </nav>
      <div className="flex-1" />
      <Link
        href="/agent-settings"
        className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs border transition-colors ${
          pathname.startsWith("/agent-settings")
            ? "bg-zinc-800 text-zinc-100 border-zinc-600"
            : "text-zinc-400 border-transparent hover:text-zinc-200 hover:bg-zinc-900"
        }`}
      >
        <Settings className="w-3.5 h-3.5" />
        {t("settings")}
      </Link>
    </header>
  );
}
