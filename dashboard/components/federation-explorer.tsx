"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fetchFederatedStats,
  fetchFederatedQuery,
  fetchFederatedReferences,
} from "@/lib/api";
import type {
  FederatedStats,
  FederatedQueryResult,
  FederatedReference,
} from "@/lib/api";
import { Network, Search, Code2, FolderGit2 } from "lucide-react";

export function FederationExplorer() {
  const t = useTranslations("Federation");
  const [stats, setStats] = useState<FederatedStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"search" | "references">("search");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<FederatedQueryResult["results"]>([]);
  const [referenceResults, setReferenceResults] = useState<FederatedReference[]>([]);

  useEffect(() => {
    fetchFederatedStats()
      .then((data) => setStats(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function handleSearch(term?: string, searchMode?: "search" | "references") {
    const q = (term !== undefined ? term : query).trim();
    const m = searchMode || mode;
    if (!q) return;

    setSearching(true);
    try {
      if (m === "search") {
        const res = await fetchFederatedQuery(q);
        setSearchResults(res.results || []);
        setReferenceResults([]);
      } else {
        const res = await fetchFederatedReferences(q);
        setReferenceResults(res.references || []);
        setSearchResults([]);
      }
    } catch {
      setSearchResults([]);
      setReferenceResults([]);
    } finally {
      setSearching(false);
    }
  }

  function handleSelectSymbol(symbol: string) {
    setQuery(symbol);
    setMode("references");
    handleSearch(symbol, "references");
  }

  return (
    <Card className="bg-zinc-950 border-zinc-800 text-zinc-100">
      <CardHeader className="border-b border-zinc-900 pb-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-indigo-950/60 text-indigo-400 border border-indigo-900/50">
              <Network className="w-5 h-5" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold">{t("title")}</CardTitle>
              <p className="text-xs text-zinc-400 mt-0.5">{t("subtitle")}</p>
            </div>
          </div>
          {stats && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-zinc-300">
                {t("projectsIndexed", { count: stats.projects_indexed })}
              </span>
              <span className="px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-zinc-400">
                {t("nodesEdges", { nodes: stats.total_nodes, edges: stats.total_edges })}
              </span>
              <span className="px-2.5 py-1 rounded-md bg-indigo-950/40 border border-indigo-900/50 text-indigo-300">
                {t("sharedSymbolsCount", { count: stats.shared_symbols_count ?? stats.shared_symbols?.length ?? 0 })}
              </span>
            </div>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-4 space-y-4">
        {/* Search Bar & Mode Switcher */}
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder={t("searchPlaceholder")}
              className="w-full bg-zinc-900 border border-zinc-800 rounded-lg pl-9 pr-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-zinc-700"
            />
          </div>
          <div className="flex rounded-lg border border-zinc-800 bg-zinc-900/80 p-0.5 text-xs self-start sm:self-auto">
            <button
              onClick={() => {
                setMode("search");
                if (query.trim()) handleSearch(query, "search");
              }}
              className={`px-3 py-1.5 rounded-md transition-colors ${
                mode === "search"
                  ? "bg-zinc-800 text-zinc-100 shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t("modeSearch")}
            </button>
            <button
              onClick={() => {
                setMode("references");
                if (query.trim()) handleSearch(query, "references");
              }}
              className={`px-3 py-1.5 rounded-md transition-colors ${
                mode === "references"
                  ? "bg-zinc-800 text-zinc-100 shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t("modeReferences")}
            </button>
          </div>
        </div>

        {/* Top Shared Symbols Chips */}
        {stats?.shared_symbols && stats.shared_symbols.length > 0 && (
          <div className="space-y-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              {t("sharedSymbolsHeading")}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {stats.shared_symbols.slice(0, 15).map((item) => (
                <button
                  key={item.symbol}
                  onClick={() => handleSelectSymbol(item.symbol)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs border transition-all ${
                    query === item.symbol && mode === "references"
                      ? "bg-indigo-950/80 border-indigo-700 text-indigo-200"
                      : "bg-zinc-900/90 hover:bg-zinc-850 border-zinc-800 hover:border-zinc-700 text-zinc-300"
                  }`}
                >
                  <Code2 className="w-3 h-3 text-indigo-400" />
                  <span className="font-mono">{item.symbol}</span>
                  <Badge variant="secondary" className="px-1 py-0 text-[10px] bg-zinc-800 text-zinc-400">
                    {item.count}
                  </Badge>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Results view */}
        <div className="pt-2">
          {searching && (
            <div className="py-6 text-center text-xs text-zinc-500 animate-pulse">
              {t("searching")}
            </div>
          )}

          {!searching && mode === "search" && searchResults.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {searchResults.map((r, i) => (
                <div
                  key={`${r.project}-${r.id}-${i}`}
                  className="p-3 rounded-lg border border-zinc-800/80 bg-zinc-900/50 hover:border-zinc-700/80 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <span className="font-mono text-xs font-medium text-indigo-300 truncate">
                      {r.id}
                    </span>
                    <Badge variant="outline" className="text-[10px] uppercase border-zinc-700 text-zinc-400">
                      {r.kind}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-zinc-400 mt-2 pt-2 border-t border-zinc-850">
                    <span className="flex items-center gap-1">
                      <FolderGit2 className="w-3 h-3 text-zinc-500" />
                      {r.project}
                    </span>
                    <span className="text-zinc-500">
                      {(r.semantic_score * 100).toFixed(0)}% match
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!searching && mode === "references" && referenceResults.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {referenceResults.map((ref, i) => (
                <div
                  key={`${ref.project}-${ref.id}-${i}`}
                  className="p-3 rounded-lg border border-zinc-800/80 bg-zinc-900/50 hover:border-zinc-700/80 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-mono text-xs font-medium text-emerald-300 truncate">
                      {ref.label || ref.id}
                    </span>
                    <span className="text-[10px] text-zinc-500">
                      {t("degree", { deg: ref.degree })}
                    </span>
                  </div>
                  <div className="text-[11px] font-mono text-zinc-400 truncate mb-2">
                    {ref.file || ref.id}
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-zinc-400 pt-1.5 border-t border-zinc-850">
                    <span className="flex items-center gap-1 text-zinc-300">
                      <FolderGit2 className="w-3 h-3 text-zinc-500" />
                      {ref.project}
                    </span>
                    <Badge variant="outline" className="text-[10px] border-zinc-800 text-zinc-400">
                      {ref.kind}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!searching && query.trim() !== "" && searchResults.length === 0 && referenceResults.length === 0 && (
            <div className="py-6 text-center text-xs text-zinc-500">
              {t("noResults")}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
