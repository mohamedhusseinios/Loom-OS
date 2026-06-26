"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProject, discoverDirs } from "@/lib/api";
import { Folder, FolderGit2, ChevronRight, Loader2 } from "lucide-react";

interface AddProjectModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function AddProjectModal({ open, onClose, onCreated }: AddProjectModalProps) {
  const t = useTranslations("AddProjectModal");
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<"browse" | "manual">("browse");
  const [currentPath, setCurrentPath] = useState("~");
  const [dirs, setDirs] = useState<{ name: string; path: string; has_git: boolean }[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualPath, setManualPath] = useState("");

  // Drive the native dialog. showModal()/close() give us Escape handling,
  // focus trapping, and the ::backdrop overlay for free.
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  // Sync parent state when the dialog is dismissed natively (Escape). The
  // `close` event fires after any close; we only need to notify React if the
  // `open` prop hasn't already flipped to false (i.e. it wasn't our doing).
  const onNativeClose = () => {
    if (open) onClose();
  };

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
      setError(t("browseError"));
    } finally {
      setLoading(false);
    }
  }

  function handleNavigate(dir: { name: string; path: string }) {
    setCurrentPath(dir.path);
  }

  async function handleUseCurrentFolder() {
    setLoading(true);
    setError("");
    try {
      const name = currentPath === "~"
        ? "home"
        : currentPath.split("/").pop() || currentPath;
      await createProject({ name, path: currentPath });
      onCreated();
      onClose();
    } catch {
      setError(t("createError"));
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
      setError(t("createError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onNativeClose}
      // Backdrop click: the click lands on the <dialog> element itself (not a
      // child), since the panel fills the dialog's content area.
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="rounded-xl p-0 bg-transparent max-w-none"
    >
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[480px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">{t("heading")}</h2>

        <div className="flex gap-2 mb-4">
          <Button
            variant={tab === "browse" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("browse")}
          >
            {t("browseDisk")}
          </Button>
          <Button
            variant={tab === "manual" ? "default" : "outline"}
            size="sm"
            onClick={() => setTab("manual")}
          >
            {t("manualEntry")}
          </Button>
        </div>

        {tab === "browse" ? (
          <div>
            {parent && (
              <button
                onClick={() => setCurrentPath(parent)}
                className="text-sm text-zinc-400 hover:text-zinc-200 mb-2 flex items-center gap-1"
              >
                {/* "up one level" — chevron flips with text direction */}
                <ChevronRight className="w-3 h-3 rotate-180 rtl:rotate-0" /> {parent}
              </button>
            )}
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-zinc-500 font-mono truncate">{currentPath}</span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleUseCurrentFolder}
                disabled={loading}
                className="text-xs h-7"
              >
                {loading ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  t("selectThisFolder")
                )}
              </Button>
            </div>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-zinc-500" />
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto space-y-1">
                {dirs.map((d) => (
                  <button
                    key={d.path}
                    onClick={() => handleNavigate(d)}
                    className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-zinc-800 text-start text-sm text-zinc-300"
                  >
                    {d.has_git ? (
                      <FolderGit2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    ) : (
                      <Folder className="w-4 h-4 text-zinc-500 flex-shrink-0" />
                    )}
                    <span className="flex-1 truncate">{d.name}</span>
                    <ChevronRight className="w-3 h-3 text-zinc-600 flex-shrink-0" />
                  </button>
                ))}
                {dirs.length === 0 && (
                  <p className="text-sm text-zinc-600 py-4 text-center">{t("noSubdirs")}</p>
                )}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleManualCreate} className="space-y-3">
            <Input
              placeholder={t("namePlaceholder")}
              value={manualName}
              onChange={(e) => setManualName(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
            <Input
              placeholder={t("pathPlaceholder")}
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : t("create")}
            </Button>
          </form>
        )}

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <Button variant="ghost" size="sm" onClick={onClose} className="mt-3 w-full">
          {t("cancel")}
        </Button>
      </div>
    </dialog>
  );
}
