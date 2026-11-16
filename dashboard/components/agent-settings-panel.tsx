"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  getAgentSettings,
  listProviderModels,
  updateAgentSettings,
  type AgentProvider,
  type AgentSettings,
} from "@/lib/api";

const FIELD_CLASS = "mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100";
const OLLAMA_DEFAULT_BASE = "http://localhost:11434";
const DECISION_IDS = new Set(["typesafe", "ollama", "gliclass"]);
const PRESET_CHAT_IDS = new Set(["deepseek", "openai", "anthropic"]);

type DecisionModel = "" | "typesafe" | "ollama" | "gliclass";
type JudgmentBackend = "typesafe" | "ollama" | "none";
type ApiStyle = "openai" | "anthropic";

type ChatDraft = {
  id: string;
  name: string;
  base_url: string;
  api_style: ApiStyle;
  model_ids: string[];
  api_key: string;
};

function providerBase(settings: AgentSettings | null, id: string): string {
  return settings?.providers?.find((p) => p.id === id)?.base_url || "";
}

function providerModel(settings: AgentSettings | null, id: string, fallback: string): string {
  const ids = settings?.providers?.find((p) => p.id === id)?.model_ids ?? [];
  const found = ids.find((item) => item.trim());
  return found ? found.trim() : fallback;
}

function providerWithModel(settings: AgentSettings | null, id: string, fallbackName: string, baseUrl: string, model: string) {
  const current = settings?.providers?.find((p) => p.id === id);
  return {
    id,
    name: current?.name || fallbackName,
    base_url: baseUrl,
    model_ids: model.trim() ? [model.trim()] : [],
    api_style: (current?.api_style as ApiStyle | undefined) || "openai",
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

function isChatProvider(p: AgentProvider): boolean {
  return !DECISION_IDS.has(p.id);
}

function defaultBaseFor(id: string, style: ApiStyle): string {
  if (id === "deepseek") return "https://api.deepseek.com";
  if (id === "openai") return "https://api.openai.com";
  if (id === "anthropic" || style === "anthropic") return "https://api.anthropic.com";
  return "https://api.deepseek.com";
}

function toChatDrafts(settings: AgentSettings | null): ChatDraft[] {
  const rows = (settings?.providers || []).filter(isChatProvider);
  if (!rows.length) {
    return [{
      id: "deepseek",
      name: "DeepSeek",
      base_url: "https://api.deepseek.com",
      api_style: "openai",
      model_ids: ["deepseek-chat"],
      api_key: "",
    }];
  }
  return rows.map((p) => ({
    id: p.id,
    name: p.name || p.id,
    base_url: p.base_url || defaultBaseFor(p.id, (p.api_style as ApiStyle) || "openai"),
    api_style: (p.api_style as ApiStyle) || (p.id === "anthropic" ? "anthropic" : "openai"),
    model_ids: p.model_ids?.length ? [...p.model_ids] : [],
    api_key: "",
  }));
}

function newCustomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `custom-${crypto.randomUUID().slice(0, 8)}`;
  }
  return `custom-${Date.now().toString(36)}`;
}

export function AgentSettingsPanel() {
  const t = useTranslations("LoomAgent");
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [chatDrafts, setChatDrafts] = useState<ChatDraft[]>([]);
  const [chatProvider, setChatProvider] = useState("deepseek");
  const [model, setModel] = useState("deepseek-chat");
  const [listedModels, setListedModels] = useState<string[]>([]);
  const [listing, setListing] = useState(false);
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
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const typesafeKeySet = Boolean(settings?.has_keys?.typesafe) || Boolean(jevKey.trim());
  const showTypesafe = decisionModel === "" || decisionModel === "typesafe" || (decisionModel === "gliclass" && judgmentProvider === "typesafe");
  const showOllama = decisionModel === "ollama" || (decisionModel === "gliclass" && judgmentProvider === "ollama");
  const showGliclass = decisionModel === "gliclass";

  const activeDraft = useMemo(
    () => chatDrafts.find((d) => d.id === chatProvider) || chatDrafts[0] || null,
    [chatDrafts, chatProvider],
  );

  function applySettings(s: AgentSettings) {
    setSettings(s);
    const drafts = toChatDrafts(s);
    setChatDrafts(drafts);
    const active = s.chat_provider && drafts.some((d) => d.id === s.chat_provider)
      ? s.chat_provider
      : drafts[0]?.id || "deepseek";
    setChatProvider(active);
    setModel(s.default_model || "deepseek-chat");
    const activeRow = drafts.find((d) => d.id === active);
    setListedModels(activeRow?.model_ids?.length ? [...activeRow.model_ids] : []);
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

  function updateActiveDraft(patch: Partial<ChatDraft>) {
    setChatDrafts((prev) => prev.map((d) => (d.id === chatProvider ? { ...d, ...patch } : d)));
  }

  function onChatProviderChange(id: string) {
    setChatProvider(id);
    const row = chatDrafts.find((d) => d.id === id);
    if (row?.model_ids?.length) {
      setListedModels([...row.model_ids]);
      if (!model || !row.model_ids.includes(model)) {
        setModel(row.model_ids[0]);
      }
    } else {
      setListedModels([]);
    }
  }

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

  function addCustomProvider() {
    const id = newCustomId();
    const draft: ChatDraft = {
      id,
      name: t("customProviderName"),
      base_url: "https://api.openai.com",
      api_style: "openai",
      model_ids: [],
      api_key: "",
    };
    setChatDrafts((prev) => [...prev, draft]);
    setChatProvider(id);
    setListedModels([]);
  }

  function removeCustomProvider() {
    if (!activeDraft || PRESET_CHAT_IDS.has(activeDraft.id)) return;
    const next = chatDrafts.filter((d) => d.id !== activeDraft.id);
    setChatDrafts(next);
    const fallback = next[0]?.id || "deepseek";
    setChatProvider(fallback);
    const row = next.find((d) => d.id === fallback);
    setListedModels(row?.model_ids?.length ? [...row.model_ids] : []);
  }

  async function fetchModels() {
    if (!activeDraft) return;
    setListing(true);
    setMsg("");
    try {
      const result = await listProviderModels({
        provider_id: activeDraft.id,
        base_url: activeDraft.base_url.trim() || undefined,
        api_style: activeDraft.api_style,
        api_key: activeDraft.api_key.trim() || undefined,
      });
      setListedModels(result.models);
      updateActiveDraft({ model_ids: result.models });
      if (result.models.length && !result.models.includes(model)) {
        setModel(result.models[0]);
      }
      setMsg(t("modelsLoaded", { count: result.models.length }));
    } catch (err) {
      setMsg(err instanceof Error && err.message ? err.message : t("modelsLoadError"));
    } finally {
      setListing(false);
    }
  }

  async function save() {
    if (!activeDraft) return;
    setSaving(true);
    setMsg("");
    try {
      const api_keys: Record<string, string> = {};
      for (const draft of chatDrafts) {
        if (draft.api_key.trim()) api_keys[draft.id] = draft.api_key.trim();
      }
      if (showTypesafe && jevKey.trim()) api_keys.typesafe = jevKey.trim();
      if (showOllama && ollamaKey.trim()) api_keys.ollama = ollamaKey.trim();
      if (showGliclass && gliclassKey.trim()) api_keys.gliclass = gliclassKey.trim();

      const chatProviders = chatDrafts.map((d) => {
        const models = d.id === chatProvider
          ? (listedModels.length ? listedModels : (model.trim() ? [model.trim()] : d.model_ids))
          : d.model_ids;
        const mergedModels = d.id === chatProvider && model.trim() && !models.includes(model.trim())
          ? [model.trim(), ...models]
          : models;
        return {
          id: d.id,
          name: d.name.trim() || d.id,
          base_url: d.base_url.trim() || defaultBaseFor(d.id, d.api_style),
          model_ids: mergedModels,
          api_style: d.api_style,
        };
      });

      const providers = [...chatProviders];
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
        chat_provider: chatProvider,
        providers,
        ...(Object.keys(api_keys).length ? { api_keys } : {}),
        ...(roles ?? {}),
      });
      applySettings(next);
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
      if (providerId === "typesafe") setJevKey("");
      if (providerId === "ollama") setOllamaKey("");
      if (providerId === "gliclass") setGliclassKey("");
      setChatDrafts((prev) => prev.map((d) => (d.id === providerId ? { ...d, api_key: "" } : d)));
      setMsg(t("keyCleared"));
    } catch (err) {
      setMsg(err instanceof Error && err.message ? err.message : t("keyClearError"));
    } finally {
      setClearing(null);
    }
  }

  const hasTypesafe = Boolean(settings?.has_keys?.typesafe);
  const hasOllama = Boolean(settings?.has_keys?.ollama);
  const hasGliclass = Boolean(settings?.has_keys?.gliclass);
  const hasActiveKey = Boolean(settings?.has_keys?.[chatProvider]);

  function keyStatus(configured: boolean) {
    return (
      <span className="ms-2 text-[10px] uppercase tracking-wide text-zinc-500">
        {configured ? t("keyConfigured") : t("keyMissing")}
      </span>
    );
  }

  const modelOptions = useMemo(() => {
    const set = new Set<string>([...listedModels, ...(activeDraft?.model_ids || [])]);
    if (model.trim()) set.add(model.trim());
    return Array.from(set);
  }, [listedModels, activeDraft, model]);

  return (
    <div className="rounded-lg border border-zinc-800 p-3 space-y-3">
      <h3 className="text-sm font-semibold text-zinc-200">{t("settingsTitle")}</h3>

      <div className="space-y-2 rounded border border-zinc-800/80 p-2">
        <p className="text-xs font-medium text-zinc-300">{t("chatProvidersTitle")}</p>
        <label className="block text-xs text-zinc-400">
          {t("chatProvider")}
          <select
            className={FIELD_CLASS}
            value={chatProvider}
            onChange={(e) => onChatProviderChange(e.target.value)}
          >
            {chatDrafts.map((d) => (
              <option key={d.id} value={d.id}>{d.name || d.id}</option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" onClick={addCustomProvider} disabled={saving}>
            {t("addCustomProvider")}
          </Button>
          {activeDraft && !PRESET_CHAT_IDS.has(activeDraft.id) && (
            <Button size="sm" variant="ghost" onClick={removeCustomProvider} disabled={saving}>
              {t("removeProvider")}
            </Button>
          )}
        </div>
        {activeDraft && !PRESET_CHAT_IDS.has(activeDraft.id) && (
          <label className="block text-xs text-zinc-400">
            {t("providerName")}
            <input
              className={FIELD_CLASS}
              value={activeDraft.name}
              onChange={(e) => updateActiveDraft({ name: e.target.value })}
            />
          </label>
        )}
        <label className="block text-xs text-zinc-400">
          {t("apiStyle")}
          <select
            className={FIELD_CLASS}
            value={activeDraft?.api_style || "openai"}
            onChange={(e) => updateActiveDraft({ api_style: e.target.value as ApiStyle })}
            disabled={activeDraft?.id === "anthropic" || activeDraft?.id === "deepseek" || activeDraft?.id === "openai"}
          >
            <option value="openai">{t("apiStyleOpenai")}</option>
            <option value="anthropic">{t("apiStyleAnthropic")}</option>
          </select>
        </label>
        <label className="block text-xs text-zinc-400">
          {t("providerBaseUrl")}
          <input
            className={FIELD_CLASS}
            value={activeDraft?.base_url || ""}
            onChange={(e) => updateActiveDraft({ base_url: e.target.value })}
          />
        </label>
        <label className="block text-xs text-zinc-400">
          {t("apiKey")}
          {keyStatus(hasActiveKey)}
          <input
            type="password"
            autoComplete="off"
            className={FIELD_CLASS}
            placeholder={settings?.api_keys_masked?.[chatProvider] || t("apiKeyPlaceholder")}
            value={activeDraft?.api_key || ""}
            onChange={(e) => updateActiveDraft({ api_key: e.target.value })}
          />
        </label>
        {hasActiveKey && (
          <Button size="sm" variant="ghost" onClick={() => void clearKey(chatProvider)} disabled={clearing !== null || saving}>
            {clearing === chatProvider ? t("clearing") : t("clearKey")}
          </Button>
        )}
        <label className="block text-xs text-zinc-400">
          {t("defaultModel")}
          <input
            className={FIELD_CLASS}
            list="loom-chat-models"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <datalist id="loom-chat-models">
            {modelOptions.map((id) => (
              <option key={id} value={id} />
            ))}
          </datalist>
        </label>
        <Button size="sm" variant="ghost" onClick={() => void fetchModels()} disabled={listing || saving}>
          {listing ? t("gettingModels") : t("getModels")}
        </Button>
      </div>

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
