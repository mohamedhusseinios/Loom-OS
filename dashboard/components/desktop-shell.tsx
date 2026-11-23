"use client";

import { usePathname } from "@/i18n/navigation";
import { Sidebar } from "@/components/sidebar";
import { DesktopAppChrome } from "@/components/desktop-app-chrome";

/** App chrome + optional sidebar. Agent surface is full-bleed under the chrome; Dashboard keeps the sidebar. */
export function DesktopShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAgentApp = pathname.startsWith("/agent-app");

  return (
    <div className="flex flex-col min-h-screen">
      <DesktopAppChrome />
      {isAgentApp ? (
        <main className="flex-1 min-h-0 flex flex-col">{children}</main>
      ) : (
        <div className="flex flex-1 min-h-0">
          <Sidebar />
          <main className="flex-1 p-6">{children}</main>
        </div>
      )}
    </div>
  );
}
