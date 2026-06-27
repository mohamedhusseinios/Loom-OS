"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { registerAgent, listKnownAgents, KnownAgent } from "@/lib/api";
import { Loader2, UserPlus, Check, Search } from "lucide-react";

interface RegisterAgentModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  projectPath: string;
  onRegistered: () => void;
}

export function RegisterAgentModal({
  open,
  onClose,
  projectId,
  projectPath,
  onRegistered,
}: RegisterAgentModalProps) {
  const t = useTranslations("RegisterAgentModal");
  const ref = useRef<HTMLDialogElement>(null);
  const [agent, setAgent] = useState("");
  const [path, setPath] = useState(projectPath || "");
  const [version, setVersion] = useState("1.0");
  const [capabilities, setCapabilities] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [knownAgents, setKnownAgents] = useState<KnownAgent[]>([]);
  const [loadingKnown, setLoadingKnown] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    if (open) {
      setPath(projectPath || "");
      setError("");
      // Fetch known agents
      setLoadingKnown(true);
      listKnownAgents()
        .then((data) => setKnownAgents(data.agents))
        .catch(() => setKnownAgents([]))
        .finally(() => setLoadingKnown(false));
    }
  }, [open, projectPath]);

  const onNativeClose = () => {
    if (open) onClose();
  };

  function selectKnownAgent(ka: KnownAgent) {
    setAgent(ka.name);
    setVersion(ka.default_version);
    setCapabilities(ka.default_capabilities.join(", "));
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await registerAgent(projectId, {
        agent,
        version: version || "1.0",
        project_path: path,
        capabilities: capabilities
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
      });
      onRegistered();
      onClose();
    } catch {
      setError(t("registerError"));
    } finally {
      setLoading(false);
    }
  }

  const installedAgents = knownAgents.filter((a) => a.installed);
  const otherAgents = knownAgents.filter((a) => !a.installed);

  return (
    <dialog
      ref={ref}
      onClose={onNativeClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 m-auto h-fit w-fit rounded-xl p-0 bg-transparent max-w-none"
    >
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[520px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">
          <UserPlus className="w-4 h-4 inline me-2" />
          {t("heading")}
        </h2>

        {/* Detected agents quick-pick */}
        {!loadingKnown && installedAgents.length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-zinc-500 mb-2 flex items-center gap-1">
              <Search className="w-3 h-3" /> {t("detectedOnMachine")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {installedAgents.map((ka) => (
                <button
                  key={ka.name}
                  type="button"
                  onClick={() => selectKnownAgent(ka)}
                  className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
                    agent === ka.name
                      ? "border-emerald-600 bg-emerald-900/30 text-emerald-300"
                      : "border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-zinc-600"
                  }`}
                >
                  {agent === ka.name && <Check className="w-3 h-3 inline me-1" />}
                  {ka.display}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Other known agents (not installed) */}
        {!loadingKnown && otherAgents.length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-zinc-600 mb-2">{t("otherAgents")}</p>
            <div className="flex flex-wrap gap-1.5">
              {otherAgents.map((ka) => (
                <button
                  key={ka.name}
                  type="button"
                  onClick={() => selectKnownAgent(ka)}
                  className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors opacity-60 hover:opacity-100 ${
                    agent === ka.name
                      ? "border-zinc-600 bg-zinc-800 text-zinc-300"
                      : "border-zinc-800 bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {ka.display}
                </button>
              ))}
            </div>
          </div>
        )}

        <form onSubmit={handleRegister} className="space-y-3">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("agentName")}</label>
            <Input
              placeholder={t("agentNamePlaceholder")}
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
          </div>

          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("projectPath")}</label>
            <Input
              placeholder={t("pathPlaceholder")}
              value={path}
              onChange={(e) => setPath(e.target.value)}
              className="bg-zinc-800 border-zinc-700 text-zinc-200"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">{t("version")}</label>
              <Input
                placeholder="1.0"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                className="bg-zinc-800 border-zinc-700 text-zinc-200"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">{t("capabilities")}</label>
              <Input
                placeholder={t("capabilitiesPlaceholder")}
                value={capabilities}
                onChange={(e) => setCapabilities(e.target.value)}
                className="bg-zinc-800 border-zinc-700 text-zinc-200"
              />
            </div>
          </div>

          <Button type="submit" disabled={loading} className="w-full">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : t("register")}
          </Button>
        </form>

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <Button variant="ghost" size="sm" onClick={onClose} className="mt-3 w-full">
          {t("cancel")}
        </Button>
      </div>
    </dialog>
  );
}
