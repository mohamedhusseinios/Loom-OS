"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { getAgentSettings, updateAgentSettings, type AgentSettings } from "@/lib/api";

const FIELD_CLASS = "mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100";
const OLLAMA_DEFAULT_BASE = "http://localhost:11434";

type DecisionModel = "" | "typesafe" | "ollama" | "gliclass";
type JudgmentBackend = "typesafe" | "ollama" | "none";

function providerBase(settings: AgentSettings | null, id: string): string {
  return settings?.providers?.find((p) => p.id === id)?.base_url || "";
}

function providerModel(settings: AgentSettings | null, id: string, fallback: string): string {
  const ids = settings?.providers?.find((p) => p.id === id)?.model_ids ?? [];
  const found = ids.find((item) => item.trim());
  return found ? found.trim() : fallback;
}

function providerPayload(settings: AgentSettings | null, id: string, fallbackName: string, baseUrl: string, fallbackModels: string[]) {
  const current = settings?.providers?.find((p) => p.id === id);
  return {
    id,
    name: current?.name || fallbackName,
    base_url: baseUrl,
    model_ids: current?.model_ids?.length ? current.model_ids : fallbackModels,
  };
}

function providerWithModel(settings: AgentSettings | null, id: string, fallbackName: string, baseUrl: string, model: string) {
  const current = settings?.providers?.find((p) => p.id === id);
  return {
    id,
    name: current?.name || fallbackName,
    base_url: baseUrl,
    model_ids: model.trim() ? [model.trim()] : [],
  };
}

function isDecisionModel(value: string | null | undefined): value is Exclude<DecisionModel, ""> {
  return value === "typesafe" || value === "ollama" || value === "gliclass";
}

function isJudgmentBackend(value: string | null | undefined): value is JudgmentBackend {
  return value === "typesafe" || value === "ollama" || value === "none";
}

function defaultJudgment(hasTypesafeKey: boolean): JudgmentBackend {
  return hasTypesafeKey ? "typesafe" : "none";
}

export function AgentSettingsPanel() {
  const t = useTranslations("LoomAgent");
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [deepseekBase, setDeepseekBase] = useState("https://api.deepseek.com");
  const [jevKey, setJevKey] = useState("");
  const [jevBase, setJevBase] = useState("");
  const [jevModel, setJevModel] = useState("jev-latest");
  const [ollamaKey, setOllamaKey] = useState("");
  const [ollamaBase, setOllamaBase] = useState(OLLAMA_DEFAULT_BASE);
  const [ollamaModel, setOllamaModel] = useState("");
  const [gliclassKey, setGliclassKey] = useState("");
  const [gliclassBase, setGliclassBase] = useState("");
  const [gliclassModel, setGliclassModel] = useState("");
  const [decisionModel, setDecisionModel] = useState<DecisionModel>("");
  const [judgmentProvider, setJudgmentProvider] = useState<JudgmentBackend>("none");
  const [model, setModel] = useState("deepseek-chat");
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const typesafeKeySet = Boolean(settings?.has_keys?.typesafe) || Boolean(jevKey.trim());
  const showTypesafe = decisionModel === "" || decisionModel === "typesafe" || (decisionModel === "gliclass" && judgmentProvider === "typesafe");
  const showOllama = decisionModel === "ollama" || (decisionModel === "gliclass" && judgmentProvider === "ollama");
  const showGliclass = decisionModel === "gliclass";

  function applySettings(s: AgentSettings) {
    setSettings(s);
    setModel(s.default_model || "deepseek-chat");
    setDeepseekBase(providerBase(s, "deepseek") || "https://api.deepseek.com");
    setJevBase(providerBase(s, "typesafe"));
    setJevModel(providerModel(s, "typesafe", "jev-latest"));
    setOllamaBase(providerBase(s, "ollama") || OLLAMA_DEFAULT_BASE);
    setOllamaModel(providerModel(s, "ollama", ""));
    setGliclassBase(providerBase(s, "gliclass"));
    setGliclassModel(providerModel(s, "gliclass", ""));
    const decision = isDecisionModel(s.filter_provider) ? s.filter_provider : "";
    setDecisionModel(decision);
    if (decision === "typesafe" || decision === "ollama") {
      setJudgmentProvider(decision);
    } else if (isJudgmentBackend(s.judgment_provider)) {
      setJudgmentProvider(s.judgment_provider);
    } else {
      setJudgmentProvider(defaultJudgment(Boolean(s.has_keys?.typesafe)));
    }
  }

  useEffect(() => {
    getAgentSettings()
      .then(applySettings)
      .catch(() => setMsg(t("settingsLoadError")));
  }, [t]);

  function onDecisionModelChange(value: string) {
    if (!isDecisionModel(value)) {
      setDecisionModel("");
      return;
    }
    setDecisionModel(value);
    if (value === "typesafe" || value === "ollama") {
      setJudgmentProvider(value);
      return;
    }
    setJudgmentProvider(defaultJudgment(typesafeKeySet));
  }

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      const api_keys: Record<string, string> = {};
      if (apiKey.trim()) api_keys.deepseek = apiKey.trim();
      if (showTypesafe && jevKey.trim()) api_keys.typesafe = jevKey.trim();
      if (showOllama && ollamaKey.trim()) api_keys.ollama = ollamaKey.trim();
      if (showGliclass && gliclassKey.trim()) api_keys.gliclass = gliclassKey.trim();
      const providers = [
        providerPayload(settings, "deepseek", "DeepSeek", deepseekBase.trim() || "https://api.deepseek.com", ["deepseek-chat"]),
      ];
      if (showTypesafe) {
        providers.push(providerWithModel(settings, "typesafe", "TypeSafe (Jev)", jevBase.trim(), jevModel.trim() || "jev-latest"));
      }
      if (showOllama) {
        providers.push(providerWithModel(settings, "ollama", "Ollama", ollamaBase.trim() || OLLAMA_DEFAULT_BASE, ollamaModel));
      }
      if (showGliclass) {
        providers.push(providerWithModel(settings, "gliclass", "GLiClass", gliclassBase.trim(), gliclassModel));
      }
      const roles = decisionModel === "typesafe" || decisionModel === "ollama"
        ? { filter_provider: decisionModel, judgment_provider: decisionModel }
        : decisionModel === "gliclass"
          ? {
              filter_provider: "gliclass" as const,
              judgment_provider: isJudgmentBackend(judgmentProvider) ? judgmentProvider : defaultJudgment(typesafeKeySet),
            }
          : null;
      const next = await updateAgentSettings({
        default_model: model,
        providers,
        ...(Object.keys(api_keys).length ? { api_keys } : {}),
        ...(roles ?? {}),
      });
      applySettings(next);
      setApiKey("");
      setJevKey("");
      setOllamaKey("");
      setGliclassKey("");
      setMsg(t("settingsSaved"));
    } catch (err) {
      setMsg(err instanceof Error && err.message ? err.message : t("settingsSaveError"));
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
      if (providerId === "ollama") setOllamaKey("");
      if (providerId === "gliclass") setGliclassKey("");
      setMsg(t("keyCleared"));
    } catch (err) {
      setMsg(err instanceof Error && err.message ? err.message : t("keyClearError"));
    } finally {
      setClearing(null);
    }
  }

  const hasDeepseek = Boolean(settings?.has_keys?.deepseek);
  const hasTypesafe = Boolean(settings?.has_keys?.typesafe);
  const hasOllama = Boolean(settings?.has_keys?.ollama);
  const hasGliclass = Boolean(settings?.has_keys?.gliclass);

  function keyStatus(configured: boolean) {
    return (
      <span className="ms-2 text-[10px] uppercase tracking-wide text-zinc-500">
        {configured ? t("keyConfigured") : t("keyMissing")}
      </span>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 p-3 space-y-3">
      <h3 className="text-sm font-semibold text-zinc-200">{t("settingsTitle")}</h3>
      <label className="block text-xs text-zinc-400">
        {t("defaultModel")}
        <input
          className={FIELD_CLASS}
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
      </label>
      <label className="block text-xs text-zinc-400">
        {t("apiKey")}
        {keyStatus(hasDeepseek)}
        <input
          type="password"
          autoComplete="off"
          className={FIELD_CLASS}
          placeholder={settings?.api_keys_masked?.deepseek || t("apiKeyPlaceholder")}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </label>
      {hasDeepseek && (
        <Button size="sm" variant="ghost" onClick={() => void clearKey("deepseek")} disabled={clearing !== null || saving}>
          {clearing === "deepseek" ? t("clearing") : t("clearKey")}
        </Button>
      )}
      <label className="block text-xs text-zinc-400">
        {t("deepseekBaseUrl")}
        <input
          className={FIELD_CLASS}
          value={deepseekBase}
          onChange={(e) => setDeepseekBase(e.target.value)}
        />
      </label>
      <label className="block text-xs text-zinc-400">
        {t("decisionModel")}
        <select
          className={FIELD_CLASS}
          value={decisionModel}
          onChange={(e) => onDecisionModelChange(e.target.value)}
        >
          <option value="" disabled={decisionModel !== ""}>{t("decisionModelPlaceholder")}</option>
          <option value="typesafe">{t("decisionTypesafe")}</option>
          <option value="ollama">{t("decisionOllama")}</option>
          <option value="gliclass">{t("decisionGliclass")}</option>
        </select>
      </label>
      <p className="text-[11px] text-zinc-500">{t("decisionHint")}</p>
      {showGliclass && (
        <label className="block text-xs text-zinc-400">
          {t("judgmentBackend")}
          <select
            className={FIELD_CLASS}
            value={judgmentProvider}
            onChange={(e) => {
              if (isJudgmentBackend(e.target.value)) setJudgmentProvider(e.target.value);
            }}
          >
            <option value="typesafe">{t("judgmentTypesafe")}</option>
            <option value="ollama">{t("judgmentOllama")}</option>
            <option value="none">{t("judgmentNone")}</option>
          </select>
        </label>
      )}
      {showTypesafe && (
        <>
          <label className="block text-xs text-zinc-400">
            {t("jevApiKey")}
            {keyStatus(hasTypesafe)}
            <input
              type="password"
              autoComplete="off"
              className={FIELD_CLASS}
              placeholder={settings?.api_keys_masked?.typesafe || t("jevApiKeyPlaceholder")}
              value={jevKey}
              onChange={(e) => setJevKey(e.target.value)}
            />
          </label>
          {hasTypesafe && (
            <Button size="sm" variant="ghost" onClick={() => void clearKey("typesafe")} disabled={clearing !== null || saving}>
              {clearing === "typesafe" ? t("clearing") : t("clearKey")}
            </Button>
          )}
          <label className="block text-xs text-zinc-400">
            {t("jevBaseUrl")}
            <input
              className={FIELD_CLASS}
              placeholder={t("jevBaseUrlPlaceholder")}
              value={jevBase}
              onChange={(e) => setJevBase(e.target.value)}
            />
          </label>
          <label className="block text-xs text-zinc-400">
            {t("jevModel")}
            <input
              className={FIELD_CLASS}
              value={jevModel}
              onChange={(e) => setJevModel(e.target.value)}
            />
          </label>
        </>
      )}
      {showOllama && (
        <>
          <label className="block text-xs text-zinc-400">
            {t("ollamaApiKey")}
            {keyStatus(hasOllama)}
            <input
              type="password"
              autoComplete="off"
              className={FIELD_CLASS}
              placeholder={settings?.api_keys_masked?.ollama || t("ollamaApiKeyPlaceholder")}
              value={ollamaKey}
              onChange={(e) => setOllamaKey(e.target.value)}
            />
          </label>
          {hasOllama && (
            <Button size="sm" variant="ghost" onClick={() => void clearKey("ollama")} disabled={clearing !== null || saving}>
              {clearing === "ollama" ? t("clearing") : t("clearKey")}
            </Button>
          )}
          <label className="block text-xs text-zinc-400">
            {t("ollamaBaseUrl")}
            <input
              className={FIELD_CLASS}
              value={ollamaBase}
              onChange={(e) => setOllamaBase(e.target.value)}
            />
          </label>
          <label className="block text-xs text-zinc-400">
            {t("ollamaModel")}
            <input
              className={FIELD_CLASS}
              placeholder={t("ollamaModelPlaceholder")}
              value={ollamaModel}
              onChange={(e) => setOllamaModel(e.target.value)}
            />
          </label>
        </>
      )}
      {showGliclass && (
        <>
          <label className="block text-xs text-zinc-400">
            {t("gliclassApiKey")}
            {keyStatus(hasGliclass)}
            <input
              type="password"
              autoComplete="off"
              className={FIELD_CLASS}
              placeholder={settings?.api_keys_masked?.gliclass || t("gliclassApiKeyPlaceholder")}
              value={gliclassKey}
              onChange={(e) => setGliclassKey(e.target.value)}
            />
          </label>
          {hasGliclass && (
            <Button size="sm" variant="ghost" onClick={() => void clearKey("gliclass")} disabled={clearing !== null || saving}>
              {clearing === "gliclass" ? t("clearing") : t("clearKey")}
            </Button>
          )}
          <label className="block text-xs text-zinc-400">
            {t("gliclassBaseUrl")}
            <input
              className={FIELD_CLASS}
              placeholder={t("gliclassBaseUrlPlaceholder")}
              value={gliclassBase}
              onChange={(e) => setGliclassBase(e.target.value)}
            />
          </label>
          <label className="block text-xs text-zinc-400">
            {t("gliclassModel")}
            <input
              className={FIELD_CLASS}
              placeholder={t("gliclassModelPlaceholder")}
              value={gliclassModel}
              onChange={(e) => setGliclassModel(e.target.value)}
            />
          </label>
        </>
      )}
      <p className="text-[11px] text-zinc-500">{t("byokHint")}</p>
      <p className="text-[11px] text-zinc-500">{t("envFallbackHint")}</p>
      <Button size="sm" onClick={() => void save()} disabled={saving || clearing !== null}>
        {saving ? t("saving") : t("saveSettings")}
      </Button>
      {msg && <p className="text-xs text-zinc-400">{msg}</p>}
    </div>
  );
}
