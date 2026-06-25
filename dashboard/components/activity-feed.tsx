"use client";

import { useEffect, useState } from "react";
import { useWebSocket } from "@/lib/use-websocket";
import { ScrollArea } from "@/components/ui/scroll-area";

interface ActivityEvent {
  id: string;
  timestamp: string;
  event: string;
  data: Record<string, unknown>;
}

export function ActivityFeed({ projectId }: { projectId: string }) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const { subscribe } = useWebSocket();

  useEffect(() => {
    return subscribe(`project:${projectId}`, (event) => {
      setEvents((prev) =>
        [
          {
            id: crypto.randomUUID(),
            timestamp: event.timestamp,
            event: event.event,
            data: event.data,
          },
          ...prev,
        ].slice(0, 50)
      );
    });
  }, [projectId, subscribe]);

  return (
    <ScrollArea className="h-64">
      <div className="space-y-2">
        {events.length === 0 && (
          <div className="text-sm text-zinc-600">Waiting for activity...</div>
        )}
        {events.map((e) => (
          <div key={e.id} className="text-sm text-zinc-400 border-b border-zinc-800/50 pb-2">
            <span className="text-zinc-600 text-xs">
              {new Date(e.timestamp).toLocaleTimeString()}
            </span>{" "}
            <span className="text-zinc-300">{formatEvent(e)}</span>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

function formatEvent(event: ActivityEvent): string {
  switch (event.event) {
    case "agent:online":
      return `${event.data.agent} came online`;
    case "graph:updated":
      return `Graph updated: +${event.data.nodes_added || 0} nodes`;
    case "finding:ingested":
      return `Finding ingested: ${event.data.file}`;
    default:
      return event.event;
  }
}
