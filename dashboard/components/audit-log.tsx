"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

interface AuditEvent {
  id: string;
  project: string;
  agent_id: string;
  action: string;
  details: Record<string, unknown>;
  timestamp: string;
}

interface AuditSummary {
  day: string;
  actions: Record<string, number>;
}

const ACTION_COLORS: Record<string, string> = {
  "agent:online": "text-emerald-400",
  "agent:dispatched": "text-amber-400",
  "finding:ingested": "text-blue-400",
  "graph:updated": "text-purple-400",
  "agent:registered": "text-cyan-400",
  error: "text-red-400",
};

export function AuditLog({ projectId }: { projectId: string }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [summary, setSummary] = useState<AuditSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`/api/projects/${projectId}/audit?limit=50`).then((r) =>
        r.json()
      ),
      fetch(`/api/projects/${projectId}/audit/summary`).then((r) =>
        r.json()
      ),
    ])
      .then(([ev, sm]) => {
        setEvents(ev.events ?? []);
        setSummary(sm.summary ?? []);
      })
      .finally(() => setLoading(false));
  }, [projectId]);

  if (loading) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardContent className="p-4">
          <p className="text-zinc-500 text-xs">Loading audit log...</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100 text-sm">Audit Log</CardTitle>
      </CardHeader>
      <CardContent>
        {/* Daily summary */}
        {summary.length > 0 && (
          <div className="mb-3 flex gap-2 flex-wrap">
            {summary.slice(0, 3).map((day) => (
              <div
                key={day.day}
                className="bg-zinc-900 border border-zinc-700 rounded p-2 text-xs"
              >
                <p className="text-zinc-400 mb-1">{day.day}</p>
                {Object.entries(day.actions).map(([action, count]) => (
                  <div key={action} className="flex items-center gap-1">
                    <span
                      className={`${ACTION_COLORS[action] ?? "text-zinc-500"}`}
                    >
                      {action}:
                    </span>
                    <span className="text-zinc-300">{count}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Recent events */}
        <ScrollArea className="h-64">
          <div className="space-y-1">
            {events.length === 0 && (
              <p className="text-zinc-500 text-xs">No audit events yet.</p>
            )}
            {events.map((e) => (
              <div
                key={e.id}
                className="flex items-center gap-2 p-1 text-xs"
              >
                <span className="text-zinc-600 w-16 flex-shrink-0">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <Badge
                  variant="outline"
                  className={`text-xs ${ACTION_COLORS[e.action] ?? ""}`}
                >
                  {e.action}
                </Badge>
                <span className="text-zinc-400">{e.agent_id}</span>
                {Object.keys(e.details).length > 0 && (
                  <span className="text-zinc-600 truncate">
                    {JSON.stringify(e.details).slice(0, 60)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
