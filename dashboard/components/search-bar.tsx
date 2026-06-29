"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SearchResult {
  id: string;
  text: string;
  score: number;
  source: string;
  kind?: string;
  semantic_score?: number;
  structural_distance?: number;
}

interface SearchBarProps {
  projectId: string;
}

export function SearchBar({ projectId }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"text" | "hybrid">("text");

  async function handleSearch(q: string) {
    setQuery(q);
    if (q.length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(
        `/api/projects/${projectId}/search?q=${encodeURIComponent(q)}&mode=${mode}`
      );
      const data = await res.json();
      setResults(data.results ?? []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  // Re-trigger search when mode flips (only if there's already a query).
  function toggleMode(next: "text" | "hybrid") {
    if (next === mode) return;
    setMode(next);
    if (query.length >= 2) {
      // Use the new mode directly to avoid stale closure.
      void runSearch(query, next);
    }
  }

  async function runSearch(q: string, searchMode: "text" | "hybrid") {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/projects/${projectId}/search?q=${encodeURIComponent(q)}&mode=${searchMode}`
      );
      const data = await res.json();
      setResults(data.results ?? []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => toggleMode("text")}
          className={cn(
            "px-2 py-0.5 text-xs rounded-md border transition-colors",
            mode === "text"
              ? "bg-emerald-600 text-white border-emerald-500"
              : "bg-zinc-900 text-zinc-400 border-zinc-700 hover:text-zinc-200"
          )}
        >
          Text
        </button>
        <button
          type="button"
          onClick={() => toggleMode("hybrid")}
          className={cn(
            "px-2 py-0.5 text-xs rounded-md border transition-colors",
            mode === "hybrid"
              ? "bg-emerald-600 text-white border-emerald-500"
              : "bg-zinc-900 text-zinc-400 border-zinc-700 hover:text-zinc-200"
          )}
        >
          Hybrid
        </button>
      </div>
      <Input
        placeholder="Search knowledge graph... (e.g. 'authentication', 'database schema')"
        value={query}
        onChange={(e) => handleSearch(e.target.value)}
        className="bg-zinc-900 border-zinc-700 text-zinc-200"
      />
      {loading && <p className="text-zinc-500 text-xs">Searching...</p>}
      {results.map((r) => (
        <Card key={r.id} className="bg-zinc-900 border-zinc-800">
          <CardContent className="p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">{r.source ?? r.kind ?? r.id}</span>
              <span className="text-xs text-emerald-400">
                {r.semantic_score != null
                  ? `sem ${r.semantic_score.toFixed(2)}`
                  : r.score != null
                    ? r.score.toFixed(2)
                    : ""}
              </span>
            </div>
            {r.structural_distance != null && (
              <div className="text-xs text-sky-400 mt-0.5">
                depth: {r.structural_distance}
              </div>
            )}
            <p className="text-zinc-300 text-xs mt-1 line-clamp-2">
              {r.text}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}