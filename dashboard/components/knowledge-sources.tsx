"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getProjectKnowledge, scanProjectKnowledge, KnowledgeSourceResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { BookOpen, CheckCircle2, Circle, Loader2, RefreshCw, FileText } from "lucide-react";

interface KnowledgeSourcesProps {
  projectId: string;
}

export function KnowledgeSources({ projectId }: KnowledgeSourcesProps) {
  const t = useTranslations("KnowledgeSources");
  const [sources, setSources] = useState<KnowledgeSourceResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    loadSources();
  }, [projectId]);

  async function loadSources() {
    setLoading(true);
    try {
      const data = await getProjectKnowledge(projectId);
      setSources(data.sources);
    } catch {
      setSources([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleScan() {
    setScanning(true);
    try {
      await scanProjectKnowledge(projectId);
      await loadSources();
    } finally {
      setScanning(false);
    }
  }

  const foundCount = sources.filter((s) => s.found).length;
  const totalCount = sources.length;

  if (loading) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t("loading")}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-zinc-300">{t("heading")}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">
            {foundCount}/{totalCount} {t("found")}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleScan}
            disabled={scanning}
            className="h-7 text-xs"
          >
            {scanning ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3" />
            )}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {sources.map((source) => (
          <div
            key={source.source_type}
            className={`flex items-start gap-2 p-2 rounded-lg border text-xs ${
              source.found
                ? "border-emerald-800/50 bg-emerald-900/10"
                : "border-zinc-800 bg-zinc-800/30 opacity-60"
            }`}
          >
            {source.found ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
            ) : (
              <Circle className="w-3.5 h-3.5 text-zinc-600 mt-0.5 flex-shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 mb-0.5">
                <FileText className="w-3 h-3 text-zinc-500 flex-shrink-0" />
                <span className="font-medium text-zinc-300 truncate">{source.display_name}</span>
              </div>
              <p className="text-zinc-500 leading-relaxed">{source.description}</p>
              {source.found && source.used_by.length > 0 && (
                <p className="text-zinc-600 mt-1">
                  {t("usedBy")}: {source.used_by.join(", ")}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
