"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProject, discoverDirs } from "@/lib/api";
import { Folder, FolderGit2, ChevronRight, Loader2, Plus } from "lucide-react";

interface AddProjectModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function AddProjectModal({ open, onClose, onCreated }: AddProjectModalProps) {
  const [tab, setTab] = useState<"browse" | "manual">("browse");
  const [currentPath, setCurrentPath] = useState("~");
  const [dirs, setDirs] = useState<{ name: string; path: string; has_git: boolean }[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualPath, setManualPath] = useState("");

  useEffect(() => {
    if (open && tab === "browse") {
      loadDirs(currentPath);
    }
  }, [open, tab, currentPath]);

  async function loadDirs(path: string) {
    setLoading(true);
    setError("");
    try {
      const data = await discoverDirs(path);
      setDirs(data.directories);
      setParent(data.parent);
    } catch {
      setError("Failed to browse directory");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(dir: { name: string; path: string }) {
    setLoading(true);
    setError("");
    try {
      await createProject({ name: dir.name, path: dir.path });
      onCreated();
      onClose();
    } catch {
      setError("Failed to create project");
    } finally {
      setLoading(false);
    }
  }

  async function handleManualCreate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await createProject({ name: manualName, path: manualPath });
      onCreated();
      onClose();
    } catch {
      setError("Failed to create project");
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[480px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">Add Project</h2>

        <div className="flex gap-2 mb-4">
          <Button
            variant={tab === "browse" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("browse")}
          >
            Browse Disk
          </Button>
          <Button
            variant={tab === "manual" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("manual")}
          >
            Manual Entry
          </Button>
        </div>

        {tab === "browse" ? (
          <div>
            {parent && (
              <button
                onClick={() => setCurrentPath(parent)}
                className="text-sm text-zinc-400 hover:text-zinc-200 mb-2 flex items-center gap-1"
              >
                <ChevronRight className="w-3 h-3 rotate-180" /> {parent}
              </button>
            )}
            <div className="text-xs text-zinc-500 mb-2 font-mono truncate">{currentPath}</div>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-zinc-500" />
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto space-y-1">
                {dirs.map((d) => (
                  <button
                    key={d.path}
                    onClick={() => handleSelect(d)}
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-zinc-800 text-left text-sm text-zinc-300"
                  >
                    {d.has_git ? (
                      <FolderGit2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    ) : (
                      <Folder className="w-4 h-4 text-zinc-500 flex-shrink-0" />
                    )}
                    <span className="flex-1 truncate">{d.name}</span>
                    <Plus className="w-3 h-3 text-zinc-600 flex-shrink-0" />
                  </button>
                ))}
                {dirs.length === 0 && (
                  <p className="text-sm text-zinc-600 py-4 text-center">No subdirectories</p>
                )}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleManualCreate} className="space-y-3">
            <Input
              placeholder="Project name"
              value={manualName}
              onChange={(e) => setManualName(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
            <Input
              placeholder="Absolute path (e.g. /Users/.../my-project)"
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Create Project"}
            </Button>
          </form>
        )}

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <Button variant="ghost" size="sm" onClick={onClose} className="mt-3 w-full">
          Cancel
        </Button>
      </div>
    </div>
  );
}
