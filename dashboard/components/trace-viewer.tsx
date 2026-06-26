"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface TraceSpan {
  id: string;
  name: string;
  kind: string;
  project: string;
  agent_id: string;
  parent_id: string | null;
  start_time: number;
  end_time: number | null;
  latency_ms: number | null;
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
  error: string | null;
}

const KIND_COLORS: Record<string, string> = {
  agent: "text-blue-400",
  tool: "text-amber-400",
  llm: "text-purple-400",
  recall: "text-emerald-400",
  retain: "text-cyan-400",
  extract: "text-pink-400",
};

export function TraceViewer() {
  const [traces, setTraces] = useState<TraceSpan[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/traces?limit=50")
      .then((r) => r.json())
      .then((d) => setTraces(d.traces ?? []))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardContent className="p-4">
          <p className="text-zinc-500 text-xs">Loading traces...</p>
        </CardContent>
      </Card>
    );
  }

  if (!traces.length) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-zinc-100 text-sm">Trace Viewer</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-zinc-500 text-xs">
            No traces recorded yet. Agent execution spans will appear here.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100 text-sm">
          Trace Viewer
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 max-h-96 overflow-y-auto">
        {traces.map((span) => (
          <div
            key={span.id}
            className="border border-zinc-800 rounded p-2 text-xs"
          >
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">
                {span.kind}
              </Badge>
              <span className={KIND_COLORS[span.kind] ?? "text-zinc-300"}>
                {span.name}
              </span>
              {span.latency_ms != null && (
                <span className="text-zinc-500 ml-auto">
                  {span.latency_ms.toFixed(1)}ms
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1 text-zinc-500">
              <span>{span.agent_id}</span>
              <span>·</span>
              <span>{span.project}</span>
              {span.error && (
                <span className="text-red-400 ml-auto">{span.error}</span>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
