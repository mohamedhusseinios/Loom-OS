"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";

interface SearchResult {
  id: string;
  text: string;
  score: number;
  source: string;
}

interface SearchBarProps {
  projectId: string;
}

export function SearchBar({ projectId }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  async function handleSearch(q: string) {
    setQuery(q);
    if (q.length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(
        `/api/projects/${projectId}/search?q=${encodeURIComponent(q)}`
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
              <span className="text-xs text-zinc-500">{r.source}</span>
              <span className="text-xs text-emerald-400">
                {r.score.toFixed(2)}
              </span>
            </div>
            <p className="text-zinc-300 text-xs mt-1 line-clamp-2">
              {r.text}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
