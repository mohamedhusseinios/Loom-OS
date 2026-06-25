"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { queryGraph } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Loader2 } from "lucide-react";

export default function GraphExplorerPage() {
  const { id } = useParams<{ id: string }>();
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<{ text: string }[]>([]);
  const [loading, setLoading] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    try {
      const data = await queryGraph(id, question);
      setResults(data.results || []);
    } catch {
      setResults([{ text: "Query failed. Is the daemon running?" }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Graph Explorer</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Ask questions about the {id} codebase knowledge graph
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What calls the auth controller?"
          className="bg-zinc-900 border-zinc-700 text-zinc-200 flex-1"
        />
        <Button type="submit" disabled={loading}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
        </Button>
      </form>

      {results.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <h3 className="text-sm text-zinc-400 mb-3">
            Results for &ldquo;{question}&rdquo;
          </h3>
          <div className="space-y-2">
            {results.map((r, i) => (
              <div
                key={i}
                className="text-sm text-zinc-300 font-mono pl-4 border-l-2 border-zinc-700"
              >
                {r.text}
              </div>
            ))}
          </div>
        </div>
      )}

      {results.length === 0 && !loading && (
        <div className="text-sm text-zinc-600">
          <p>Try asking:</p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>What are the main modules?</li>
            <li>Show me the callers of the API handler</li>
            <li>What community has the most nodes?</li>
            <li>Find surprising connections</li>
          </ul>
        </div>
      )}
    </div>
  );
}
