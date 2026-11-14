"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { getAgentSettings, updateAgentSettings, type AgentSettings } from "@/lib/api";

function providerBase(settings: AgentSettings | null, id: string): string {
  return settings?.providers?.find((p) => p.id === id)?.base_url || "";
}

function providerPayload(
  settings: AgentSettings | null,
  id: string,
  fallbackName: string,
  baseUrl: string,
  fallbackModels: string[],
) {
  const current = settings?.providers?.find((p) => p.id === id);
  return {
    id,
    name: current?.name || fallbackName,
    base_url: baseUrl,
    model_ids: current?.model_ids?.length ? current.model_ids : fallbackModels,
  };
}

export function AgentSettingsPanel() {
  const t = useTranslations("LoomAgent");
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [deepseekBase, setDeepseekBase] = useState("https://api.deepseek.com");
  const [jevKey, setJevKey] = useState("");
  const [jevBase, setJevBase] = useState("");
  const [model, setModel] = useState("deepseek-chat");
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  function applySettings(s: AgentSettings) {
    setSettings(s);
    setModel(s.default_model || "deepseek-chat");
    setDeepseekBase(providerBase(s, "deepseek") || "https://api.deepseek.com");
    setJevBase(providerBase(s, "typesafe"));
  }

  useEffect(() => {
    getAgentSettings()
      .then(applySettings)
      .catch(() => setMsg(t("settingsLoadError")));
  }, [t]);

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      const api_keys: Record<string, string> = {};
      if (apiKey.trim()) api_keys.deepseek = apiKey.trim();
      if (jevKey.trim()) api_keys.typesafe = jevKey.trim();
      const next = await updateAgentSettings({
        default_model: model,
        providers: [
          providerPayload(settings, "deepseek", "DeepSeek", deepseekBase.trim() || "https://api.deepseek.com", ["deepseek-chat"]),
          providerPayload(settings, "typesafe", "TypeSafe (Jev)", jevBase.trim(), ["jev-latest"]),
        ],
        ...(Object.keys(api_keys).length ? { api_keys } : {}),
      });
      applySettings(next);
      setApiKey("");
      setJevKey("");
      setMsg(t("settingsSaved"));
    } catch {
      setMsg(t("settingsSaveError"));
    } finally {
      setSaving(false);
    }
  }

  async function clearKey(providerId: string) {
    setClearing(providerId);
    setMsg("");
    try {
      const next = await updateAgentSettings({ api_keys: { [providerId]: "" } });
      applySettings(next);
      if (providerId === "deepseek") setApiKey("");
      if (providerId === "typesafe") setJevKey("");
      setMsg(t("keyCleared"));
    } catch {
      setMsg(t("keyClearError"));
    } finally {
      setClearing(null);
    }
  }

  const hasDeepseek = Boolean(settings?.has_keys?.deepseek);
  const hasTypesafe = Boolean(settings?.has_keys?.typesafe);

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
        <span className="ms-2 text-[10px] uppercase tracking-wide text-zinc-500">
          {hasDeepseek ? t("keyConfigured") : t("keyMissing")}
        </span>
        <input
          type="password"
          autoComplete="off"
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          placeholder={settings?.api_keys_masked?.deepseek || t("apiKeyPlaceholder")}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </label>
      {hasDeepseek && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void clearKey("deepseek")}
          disabled={clearing !== null || saving}
        >
          {clearing === "deepseek" ? t("clearing") : t("clearKey")}
        </Button>
      )}
      <label className="block text-xs text-zinc-400">
        {t("deepseekBaseUrl")}
        <input
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          value={deepseekBase}
          onChange={(e) => setDeepseekBase(e.target.value)}
        />
      </label>
      <label className="block text-xs text-zinc-400">
        {t("jevApiKey")}
        <span className="ms-2 text-[10px] uppercase tracking-wide text-zinc-500">
          {hasTypesafe ? t("keyConfigured") : t("keyMissing")}
        </span>
        <input
          type="password"
          autoComplete="off"
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          placeholder={settings?.api_keys_masked?.typesafe || t("jevApiKeyPlaceholder")}
          value={jevKey}
          onChange={(e) => setJevKey(e.target.value)}
        />
      </label>
      {hasTypesafe && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void clearKey("typesafe")}
          disabled={clearing !== null || saving}
        >
          {clearing === "typesafe" ? t("clearing") : t("clearKey")}
        </Button>
      )}
      <label className="block text-xs text-zinc-400">
        {t("jevBaseUrl")}
        <input
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          placeholder={t("jevBaseUrlPlaceholder")}
          value={jevBase}
          onChange={(e) => setJevBase(e.target.value)}
        />
      </label>
      <p className="text-[11px] text-zinc-500">{t("byokHint")}</p>
      <p className="text-[11px] text-zinc-500">{t("envFallbackHint")}</p>
      <Button size="sm" onClick={() => void save()} disabled={saving || clearing !== null}>
        {saving ? t("saving") : t("saveSettings")}
      </Button>
      {msg && <p className="text-xs text-zinc-400">{msg}</p>}
    </div>
  );
}
