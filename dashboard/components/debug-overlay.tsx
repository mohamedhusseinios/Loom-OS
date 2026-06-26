"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

interface Snapshot {
  id: string;
  project: string;
  agent_id: string;
  step: number;
  activity: string;
  context_summary: string;
  graph_nodes_added: number;
  graph_edges_added: number;
  timestamp: string;
}

export function DebugOverlay({ projectId }: { projectId: string }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    fetch(`/api/projects/${projectId}/snapshots`)
      .then((r) => r.json())
      .then((d) => setSnapshots(d.snapshots ?? []))
      .catch(() => {});
  }, [projectId]);

  // Time-travel playback: advance current step every 800ms
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev >= snapshots.length - 1) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, 800);
    return () => clearInterval(timer);
  }, [playing, snapshots.length]);

  if (!snapshots.length) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-zinc-100 text-sm">Debug Overlay</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-zinc-500 text-xs">
            No state snapshots yet. Snapshots are captured as agents work.
          </p>
        </CardContent>
      </Card>
    );
  }

  const current = snapshots[currentStep] ?? snapshots[snapshots.length - 1];

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-zinc-100 text-sm">
          Debug Overlay
        </CardTitle>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCurrentStep(Math.max(0, currentStep - 1))}
            className="text-zinc-400 hover:text-zinc-200 text-xs"
          >
            ◀
          </button>
          <button
            onClick={() => setPlaying(!playing)}
            className="text-zinc-400 hover:text-zinc-200 text-xs"
          >
            {playing ? "⏸" : "▶"}
          </button>
          <button
            onClick={() =>
              setCurrentStep(Math.min(snapshots.length - 1, currentStep + 1))
            }
            className="text-zinc-400 hover:text-zinc-200 text-xs"
          >
            ▶
          </button>
          <span className="text-zinc-500 text-xs ml-2">
            Step {currentStep + 1} / {snapshots.length}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {/* Current snapshot detail */}
        <div className="bg-zinc-900 border border-zinc-700 rounded p-3 mb-3">
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="outline" className="text-xs">
              {current.agent_id}
            </Badge>
            <span className="text-zinc-300 text-xs">Step {current.step}</span>
            <span className="text-zinc-500 text-xs ml-auto">
              {new Date(current.timestamp).toLocaleTimeString()}
            </span>
          </div>
          <p className="text-amber-400 text-xs font-mono">{current.activity}</p>
          <p className="text-zinc-500 text-xs mt-1">{current.context_summary}</p>
          <div className="flex gap-3 mt-2 text-xs text-zinc-500">
            <span>+{current.graph_nodes_added} nodes</span>
            <span>+{current.graph_edges_added} edges</span>
          </div>
        </div>

        {/* Step timeline */}
        <ScrollArea className="h-32">
          <div className="space-y-1">
            {snapshots.map((s, i) => (
              <div
                key={s.id}
                onClick={() => setCurrentStep(i)}
                className={`flex items-center gap-2 p-1 rounded cursor-pointer text-xs ${
                  i === currentStep
                    ? "bg-zinc-800"
                    : "hover:bg-zinc-800/50"
                }`}
              >
                <span
                  className={`w-2 h-2 rounded-full ${
                    i <= currentStep ? "bg-emerald-400" : "bg-zinc-700"
                  }`}
                />
                <span className="text-zinc-400 w-8">#{s.step}</span>
                <span className="text-zinc-300 truncate">{s.activity}</span>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
