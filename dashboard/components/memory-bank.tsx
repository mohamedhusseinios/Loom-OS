"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export interface RecallEntry {
  agent: string;
  task_hint: string;
  entities: string[];
  timestamp: string;
}

interface MemoryBankProps {
  entries: RecallEntry[];
}

export function MemoryBank({ entries }: MemoryBankProps) {
  if (!entries.length) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-zinc-100 text-sm">Memory Bank</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-zinc-500 text-xs">
            No recalled context yet. Agents will auto-recall relevant patterns as they work.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100 text-sm">Memory Bank</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.slice(-5).reverse().map((entry, i) => (
          <div key={i} className="border border-zinc-800 rounded p-2">
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="outline" className="text-xs">
                {entry.agent}
              </Badge>
              <span className="text-zinc-400 text-xs">
                {new Date(entry.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <p className="text-zinc-300 text-xs mb-1">
              Task: {entry.task_hint}
            </p>
            <div className="space-y-1">
              {entry.entities.map((e, j) => (
                <p key={j} className="text-emerald-400 text-xs font-mono truncate">
                  {e}
                </p>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
