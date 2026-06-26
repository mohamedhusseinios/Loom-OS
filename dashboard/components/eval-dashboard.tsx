import { useEffect, useState } from "react";
"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface EvalResult {
  id: string;
  criterion: string;
  score: "pass" | "warn" | "fail";
  confidence: number;
  details: string;
  created_at: string;
}

interface EvalPassRate {
  total: number;
  pass: number;
  warn: number;
  fail: number;
  pass_rate: number;
}

const SCORE_COLORS: Record<string, string> = {
  pass: "text-emerald-400 bg-emerald-400/10",
  warn: "text-amber-400 bg-amber-400/10",
  fail: "text-red-400 bg-red-400/10",
};

export function EvalDashboard({ projectId }: { projectId: string }) {
  return (
    <div className="space-y-4">
      <PassRateCard projectId={projectId} />
      <EvalResultsList projectId={projectId} />
    </div>
  );
}

function PassRateCard({ projectId }: { projectId: string }) {
  const [rate, setRate] = useState<EvalPassRate | null>(null);

  useEffect(() => {
    fetch(`/api/projects/${projectId}/eval/pass-rate`)
      .then((r) => r.json())
      .then(setRate)
      .catch(() => {});
  }, [projectId]);

  if (!rate || rate.total === 0) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardContent className="p-4">
          <p className="text-zinc-500 text-xs">No evaluations yet.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100 text-sm">Eval Pass Rate</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-4">
          <div className="text-center">
            <p className="text-2xl font-bold text-emerald-400">
              {(rate.pass_rate * 100).toFixed(0)}%
            </p>
            <p className="text-xs text-zinc-500">pass rate</p>
          </div>
          <div className="flex gap-3 text-xs">
            <span className="text-emerald-400">{rate.pass} pass</span>
            <span className="text-amber-400">{rate.warn} warn</span>
            <span className="text-red-400">{rate.fail} fail</span>
            <span className="text-zinc-500">({rate.total} total)</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function EvalResultsList({ projectId }: { projectId: string }) {
  const [evals, setEvals] = useState<EvalResult[]>([]);

  useEffect(() => {
    fetch(`/api/projects/${projectId}/eval`)
      .then((r) => r.json())
      .then((d) => setEvals(d.evals ?? []))
      .catch(() => {});
  }, [projectId]);

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100 text-sm">Recent Evals</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {evals.length === 0 && (
          <p className="text-zinc-500 text-xs">No recent evaluations.</p>
        )}
        {evals.map((e) => (
          <div
            key={e.id}
            className="border border-zinc-800 rounded p-2 text-xs"
          >
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className={`text-xs ${SCORE_COLORS[e.score] ?? ""}`}
              >
                {e.score}
              </Badge>
              <span className="text-zinc-300">{e.criterion}</span>
              <span className="text-zinc-500 ml-auto">
                {(e.confidence * 100).toFixed(0)}% conf.
              </span>
            </div>
            <p className="text-zinc-500 mt-1">{e.details}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}


