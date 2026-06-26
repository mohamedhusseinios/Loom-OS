"use client";

import { useEffect, useState } from "react";
import { useTranslations, useFormatter } from "next-intl";
import type { TranslationValues } from "next-intl";
import { useWebSocket } from "@/lib/use-websocket";
import { ScrollArea } from "@/components/ui/scroll-area";

interface ActivityEvent {
  id: string;
  timestamp: string;
  event: string;
  data: Record<string, unknown>;
}

export function ActivityFeed({ projectId }: { projectId: string }) {
  const t = useTranslations("ActivityFeed");
  const format = useFormatter();
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
          <div className="text-sm text-zinc-600">{t("waiting")}</div>
        )}
        {events.map((e) => (
          <div key={e.id} className="text-sm text-zinc-400 border-b border-zinc-800/50 pb-2">
            <span className="text-zinc-600 text-xs">
              {format.dateTime(new Date(e.timestamp), { timeStyle: "short" })}
            </span>{" "}
            <span className="text-zinc-300">{formatEvent(e, t)}</span>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

function formatEvent(
  event: ActivityEvent,
  t: (key: string, values?: TranslationValues) => string
): string {
  switch (event.event) {
    case "agent:online":
      return t("agentOnline", { agent: String(event.data.agent ?? "") });
    case "graph:updated":
      return t("graphUpdated", { count: Number(event.data.nodes_added) || 0 });
    case "finding:ingested":
      return t("findingIngested", { file: String(event.data.file ?? "") });
    default:
      return event.event;
  }
}
