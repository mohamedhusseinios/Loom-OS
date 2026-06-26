"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface PatternData {
  id: string;
  pattern_text: string;
  status: string;
  confidence: number;
  observation_count: number;
  projects: string[];
  agents: string[];
  first_seen: string;
  last_seen: string;
}

const STATUS_COLORS: Record<string, string> = {
  candidate: "text-zinc-400",
  verified: "text-blue-400",
  established: "text-emerald-400",
  deprecated: "text-red-400",
};

export function PatternExplorer() {
  const [patterns, setPatterns] = useState<PatternData[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"all" | "top" | "cross">("top");

  useEffect(() => {
    setLoading(true);
    const endpoint =
      view === "top"
        ? "/api/patterns/top"
        : view === "cross"
          ? "/api/patterns/cross-project"
          : "/api/patterns";
    fetch(endpoint)
      .then((r) => r.json())
      .then((d) => setPatterns(d.patterns ?? []))
      .finally(() => setLoading(false));
  }, [view]);

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-zinc-100 text-sm">
          Pattern Repository
        </CardTitle>
        <div className="flex gap-1">
          {(["top", "cross", "all"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`text-xs px-2 py-0.5 rounded ${
                view === v
                  ? "bg-zinc-700 text-zinc-200"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {loading && <p className="text-zinc-500 text-xs">Loading...</p>}
        {!loading && !patterns.length && (
          <p className="text-zinc-500 text-xs">
            No patterns discovered yet. Patterns evolve as agents report
            findings across projects.
          </p>
        )}
        {patterns.map((p) => (
          <div
            key={p.id}
            className="border border-zinc-800 rounded p-2 text-xs"
          >
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant="outline"
                className={`text-xs ${STATUS_COLORS[p.status] ?? ""}`}
              >
                {p.status}
              </Badge>
              <span className="text-zinc-300 font-mono truncate">
                {p.pattern_text}
              </span>
            </div>
            <div className="flex items-center gap-3 text-zinc-500">
              <span>
                {(p.confidence * 100).toFixed(0)}% conf.
              </span>
              <span>{p.observation_count} obs.</span>
              <span>{p.projects.length} projects</span>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
