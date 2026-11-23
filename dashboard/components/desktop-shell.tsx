"use client";

import { usePathname } from "@/i18n/navigation";
import { Sidebar } from "@/components/sidebar";
import { DesktopAppChrome } from "@/components/desktop-app-chrome";

/** App chrome + optional sidebar. Agent surface is full-bleed under the chrome; Dashboard keeps the sidebar. */
export function DesktopShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAgentSurface = pathname.startsWith("/agent-app") || pathname.startsWith("/agent-settings");

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <DesktopAppChrome />
      {isAgentSurface ? (
        <main className="flex-1 min-h-0 flex flex-col overflow-hidden px-4 pt-2">{children}</main>
      ) : (
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      )}
    </div>
  );
}
