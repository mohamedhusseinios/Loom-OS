"use client";

import { X } from "lucide-react";

interface NodeDetailProps {
  node: {
    id: string;
    label: string;
    kind: string;
    community: number;
    file: string;
  } | null;
  onClose: () => void;
}

export function NodeDetail({ node, onClose }: NodeDetailProps) {
  if (!node) return null;

  return (
    <div className="absolute bottom-4 right-4 bg-zinc-900 border border-zinc-700 rounded-lg p-3 min-w-[200px] shadow-lg z-10">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-zinc-200 font-mono truncate max-w-[160px]">
          {node.label}
        </h4>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="space-y-1 text-[11px]">
        <div className="flex justify-between">
          <span className="text-zinc-500">Kind</span>
          <span className="text-zinc-300">{node.kind}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Community</span>
          <span className="text-zinc-300">{node.community}</span>
        </div>
        {node.file && (
          <div className="flex justify-between">
            <span className="text-zinc-500">File</span>
            <span className="text-zinc-300 font-mono text-[10px] truncate max-w-[120px]">
              {node.file}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
