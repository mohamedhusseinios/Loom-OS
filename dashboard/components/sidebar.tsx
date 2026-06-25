"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const links = [{ href: "/", label: "Projects", icon: Home }];

  return (
    <aside className="w-64 border-r border-zinc-800 bg-zinc-950 min-h-screen p-4">
      <div className="mb-8">
        <h1 className="text-lg font-bold text-zinc-100">Agentic OS</h1>
        <p className="text-xs text-zinc-500">Agent Memory Fabric</p>
      </div>
      <nav className="space-y-1">
        {links.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                active
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
