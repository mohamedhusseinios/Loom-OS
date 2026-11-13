"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { getAgentSettings, updateAgentSettings, type AgentSettings } from "@/lib/api";

export function AgentSettingsPanel() {
  const t = useTranslations("LoomAgent");
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("deepseek-chat");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    getAgentSettings()
      .then((s) => {
        setSettings(s);
        setModel(s.default_model || "deepseek-chat");
      })
      .catch(() => setMsg(t("settingsLoadError")));
  }, [t]);

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      const payload: { default_model: string; api_keys?: Record<string, string> } = {
        default_model: model,
      };
      if (apiKey.trim()) payload.api_keys = { deepseek: apiKey.trim() };
      const next = await updateAgentSettings(payload);
      setSettings(next);
      setApiKey("");
      setMsg(t("settingsSaved"));
    } catch {
      setMsg(t("settingsSaveError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-800 p-3 space-y-3">
      <h3 className="text-sm font-semibold text-zinc-200">{t("settingsTitle")}</h3>
      <label className="block text-xs text-zinc-400">
        {t("defaultModel")}
        <input
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
      </label>
      <label className="block text-xs text-zinc-400">
        {t("apiKey")}
        <input
          type="password"
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          placeholder={settings?.api_keys_masked?.deepseek || t("apiKeyPlaceholder")}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </label>
      <p className="text-[11px] text-zinc-500">{t("byokHint")}</p>
      <Button size="sm" onClick={save} disabled={saving}>
        {saving ? t("saving") : t("saveSettings")}
      </Button>
      {msg && <p className="text-xs text-zinc-400">{msg}</p>}
    </div>
  );
}
