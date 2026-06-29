"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { AgentInfo, matchAgents } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Search } from "lucide-react";

interface AgentDirectoryProps {
  projectId: string;
  agents: AgentInfo[];
}

export function AgentDirectory({ projectId, agents }: AgentDirectoryProps) {
  const t = useTranslations("AgentDirectory");
  const [need, setNeed] = useState("");
  const [matches, setMatches] = useState<AgentInfo[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSearch(q: string) {
    setNeed(q);
    if (q.length < 2) {
      setMatches(null);
      return;
    }
    setLoading(true);
    try {
      const data = await matchAgents(projectId, q);
      setMatches(data.matches);
    } catch {
      setMatches([]);
    } finally {
      setLoading(false);
    }
  }

  const displayAgents = matches ?? agents;

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 rtl:right-3 rtl:left-auto" />
        <Input
          placeholder={t("searchPlaceholder")}
          value={need}
          onChange={(e) => handleSearch(e.target.value)}
          className="ps-9 bg-zinc-900 border-zinc-700 text-zinc-200 rtl:pe-9"
        />
      </div>

      {loading && <p className="text-zinc-500 text-xs">{t("searching")}</p>}

      {displayAgents.length === 0 && !loading ? (
        <p className="text-zinc-600 text-sm">{t("noAgents")}</p>
      ) : (
        <div className="space-y-2">
          {displayAgents.map((agent) => (
            <Card key={agent.agent_id} className="bg-zinc-900 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-sm text-zinc-100">{agent.agent_name}</span>
                  <span className={`text-[10px] uppercase ${
                    agent.status === "online" ? "text-emerald-400" :
                    agent.status === "working" ? "text-amber-400" : "text-zinc-500"
                  }`}>{agent.status}</span>
                </div>
                {agent.structured_capabilities && agent.structured_capabilities.length > 0 ? (
                  <div className="space-y-1 mt-2">
                    {agent.structured_capabilities.map((sc) => (
                      <div key={sc.name} className="text-xs">
                        <span className="text-indigo-400 font-medium">{sc.name}</span>
                        {sc.description && <span className="text-zinc-500"> — {sc.description}</span>}
                        {sc.tools && sc.tools.length > 0 && (
                          <span className="text-zinc-600 ms-2">tools: {sc.tools.join(", ")}</span>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {agent.capabilities.map((c) => (
                      <span key={c} className="text-[10px] bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded-full">
                        {c}
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}