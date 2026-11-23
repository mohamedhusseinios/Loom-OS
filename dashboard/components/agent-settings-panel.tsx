"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { getAgentSettings, updateAgentSettings, type AgentSettings } from "@/lib/api";

const FIELD_CLASS = "mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100";
const OLLAMA_DEFAULT_BASE = "http://localhost:11434";

const BUILTIN_PROVIDER_IDS = ["deepseek", "typesafe", "ollama", "gliclass"];
const CUSTOM_KIND = "openai_compatible";
const CUSTOM_ID_RE = /^[a-z0-9][a-z0-9_-]+$/;

// Builtin ids or a custom openai_compatible provider id.
type DecisionModel = string;
type JudgmentBackend = string;
type CustomRow = { id: string; name: string; base_url: string; model: string; key: string; isNew: boolean };
type AutonomyMinFit = "High" | "Medium" | "Low";

function customRowsFromSettings(s: AgentSettings | null): CustomRow[] {
  return (s?.providers ?? [])
    .filter((p) => p.kind === CUSTOM_KIND && !BUILTIN_PROVIDER_IDS.includes(p.id))
    .map((p) => ({ id: p.id, name: p.name, base_url: p.base_url, model: p.model_ids?.find((m) => m.trim())?.trim() ?? "", key: "", isNew: false }));
}

function isCustomId(rows: CustomRow[], value: string): boolean {
  return rows.some((r) => r.id === value);
}

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

function isDecisionModel(value: string | null | undefined, customs: CustomRow[]): value is string {
  return value === "typesafe" || value === "ollama" || value === "gliclass" || (Boolean(value) && isCustomId(customs, value as string));
}

function isJudgmentBackend(value: string | null | undefined, customs: CustomRow[]): value is string {
  return value === "typesafe" || value === "ollama" || value === "none" || (Boolean(value) && isCustomId(customs, value as string));
}

function defaultJudgment(hasTypesafeKey: boolean): JudgmentBackend {
  return hasTypesafeKey ? "typesafe" : "none";
}

function isAutonomyMinFit(value: string | null | undefined): value is AutonomyMinFit {
  return value === "High" || value === "Medium" || value === "Low";
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
  const [selectionAutonomyEnabled, setSelectionAutonomyEnabled] = useState(true);
  const [autonomyMinFit, setAutonomyMinFit] = useState<AutonomyMinFit>("High");
  const [autonomyRequireMargin, setAutonomyRequireMargin] = useState(true);
  const [model, setModel] = useState("deepseek-chat");
  const [customRows, setCustomRows] = useState<CustomRow[]>([]);
  const [deleting, setDeleting] = useState<string | null>(null);
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
    const customs = customRowsFromSettings(s);
    // Keep unsaved new rows so clearing a key or deleting another row doesn't discard them.
    setCustomRows((prev) => [...customs, ...prev.filter((r) => r.isNew && !customs.some((c) => c.id === r.id))]);
    const decision = isDecisionModel(s.filter_provider, customs) ? s.filter_provider : "";
    setDecisionModel(decision);
    if (decision === "typesafe" || decision === "ollama" || (decision !== "" && decision !== "gliclass")) {
      setJudgmentProvider(decision);
    } else if (isJudgmentBackend(s.judgment_provider, customs)) {
      setJudgmentProvider(s.judgment_provider);
    } else {
      setJudgmentProvider(defaultJudgment(Boolean(s.has_keys?.typesafe)));
    }
    setSelectionAutonomyEnabled(s.selection_autonomy_enabled ?? true);
    setAutonomyMinFit(isAutonomyMinFit(s.autonomy_min_fit) ? s.autonomy_min_fit : "High");
    setAutonomyRequireMargin(s.autonomy_require_margin ?? true);
  }

  useEffect(() => {
    getAgentSettings()
      .then(applySettings)
      .catch(() => setMsg(t("settingsLoadError")));
  }, [t]);

  function onDecisionModelChange(value: string) {
    if (!isDecisionModel(value, customRows)) {
      setDecisionModel("");
      return;
    }
    setDecisionModel(value);
    if (value !== "gliclass") {
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
      const providers: AgentSettings["providers"] = [
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
      for (const row of customRows) {
        const id = row.id.trim();
        if (!id) continue;
        providers.push({ id, name: row.name.trim() || id, base_url: row.base_url.trim(), model_ids: row.model.trim() ? [row.model.trim()] : [], kind: CUSTOM_KIND });
        if (row.key.trim()) api_keys[id] = row.key.trim();
      }
      const roles = decisionModel === "gliclass"
        ? {
            filter_provider: "gliclass" as const,
            judgment_provider: isJudgmentBackend(judgmentProvider, customRows) ? judgmentProvider : defaultJudgment(typesafeKeySet),
          }
        : decisionModel
          ? { filter_provider: decisionModel, judgment_provider: decisionModel }
          : null;
      const next = await updateAgentSettings({
        default_model: model,
        providers,
        selection_autonomy_enabled: selectionAutonomyEnabled,
        autonomy_min_fit: autonomyMinFit,
        autonomy_require_margin: autonomyRequireMargin,
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

  function updateCustomRow(index: number, patch: Partial<CustomRow>) {
    setCustomRows((rows) => rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function addCustomRow() {
    setCustomRows((rows) => [...rows, { id: "", name: "", base_url: "", model: "", key: "", isNew: true }]);
  }

  async function deleteCustomRow(index: number) {
    const row = customRows[index];
    if (!row) return;
    if (row.isNew) {
      setCustomRows((rows) => rows.filter((_, i) => i !== index));
      return;
    }
    setDeleting(row.id);
    setMsg("");
    try {
      const next = await updateAgentSettings({ remove_provider_ids: [row.id] });
      setCustomRows((rows) => rows.filter((r) => r.id !== row.id));
      applySettings(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      setMsg(/in use/i.test(message) ? t("customProviderInUseError") : message || t("settingsSaveError"));
    } finally {
      setDeleting(null);
    }
  }

  const customModelIds = customRows.map((r) => r.model.trim()).filter(Boolean);
  const customDecisionRows = customRows.filter((r) => r.id.trim() && CUSTOM_ID_RE.test(r.id.trim()));
  const busy = saving || clearing !== null || deleting !== null;

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
          list="loom-custom-model-ids"
          onChange={(e) => setModel(e.target.value)}
        />
        <datalist id="loom-custom-model-ids">
          {customModelIds.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
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
          {customDecisionRows.map((r) => (
            <option key={r.id} value={r.id}>{r.name.trim() || r.id}</option>
          ))}
        </select>
      </label>
      <p className="text-[11px] text-zinc-500">{t("decisionHint")}</p>
      <div className="border-t border-zinc-800 pt-3 space-y-2">
        <h4 className="text-xs font-medium text-zinc-300">{t("selectionAutonomyTitle")}</h4>
        <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
          <input
            type="checkbox"
            checked={selectionAutonomyEnabled}
            onChange={(e) => setSelectionAutonomyEnabled(e.target.checked)}
            className="accent-emerald-500 w-3 h-3"
          />
          {t("selectionAutonomyEnabled")}
        </label>
        <label className="block text-xs text-zinc-400">
          {t("autonomyMinFit")}
          <select
            className={FIELD_CLASS}
            value={autonomyMinFit}
            onChange={(e) => {
              if (isAutonomyMinFit(e.target.value)) setAutonomyMinFit(e.target.value);
            }}
          >
            <option value="High">{t("autonomyFitHigh")}</option>
            <option value="Medium">{t("autonomyFitMedium")}</option>
            <option value="Low">{t("autonomyFitLow")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
          <input
            type="checkbox"
            checked={autonomyRequireMargin}
            onChange={(e) => setAutonomyRequireMargin(e.target.checked)}
            className="accent-emerald-500 w-3 h-3"
          />
          {t("autonomyRequireMargin")}
        </label>
        <p className="text-[11px] text-zinc-500">{t("selectionAutonomyHint")}</p>
      </div>
      {showGliclass && (
        <label className="block text-xs text-zinc-400">
          {t("judgmentBackend")}
          <select
            className={FIELD_CLASS}
            value={judgmentProvider}
            onChange={(e) => {
              if (isJudgmentBackend(e.target.value, customRows)) setJudgmentProvider(e.target.value);
            }}
          >
            <option value="typesafe">{t("judgmentTypesafe")}</option>
            <option value="ollama">{t("judgmentOllama")}</option>
            <option value="none">{t("judgmentNone")}</option>
            {customDecisionRows.map((r) => (
              <option key={r.id} value={r.id}>{r.name.trim() || r.id}</option>
            ))}
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
      <div className="border-t border-zinc-800 pt-3 space-y-3">
        <h4 className="text-xs font-medium text-zinc-300">{t("customProvidersTitle")}</h4>
        <p className="text-[11px] text-zinc-500">{t("customProvidersHint")}</p>
        {customRows.map((row, index) => {
          const hasKey = !row.isNew && Boolean(settings?.has_keys?.[row.id]);
          return (
            <div key={row.isNew ? `new-${index}` : row.id} className="rounded border border-zinc-800 p-2 space-y-2">
              <label className="block text-xs text-zinc-400">
                {t("customProviderName")}
                <input className={FIELD_CLASS} value={row.name} onChange={(e) => updateCustomRow(index, { name: e.target.value })} />
              </label>
              <label className="block text-xs text-zinc-400">
                {t("customProviderId")}
                <input
                  className={FIELD_CLASS}
                  value={row.id}
                  disabled={!row.isNew}
                  autoComplete="off"
                  onChange={(e) => updateCustomRow(index, { id: e.target.value.toLowerCase() })}
                />
              </label>
              <label className="block text-xs text-zinc-400">
                {t("customProviderBaseUrl")}
                <input
                  className={FIELD_CLASS}
                  placeholder="https://api.example.com/v1"
                  value={row.base_url}
                  onChange={(e) => updateCustomRow(index, { base_url: e.target.value })}
                />
              </label>
              <label className="block text-xs text-zinc-400">
                {t("customProviderModel")}
                <input className={FIELD_CLASS} value={row.model} onChange={(e) => updateCustomRow(index, { model: e.target.value })} />
              </label>
              <label className="block text-xs text-zinc-400">
                {t("customProviderKey")}
                {!row.isNew && keyStatus(hasKey)}
                <input
                  type="password"
                  autoComplete="off"
                  className={FIELD_CLASS}
                  placeholder={(!row.isNew && settings?.api_keys_masked?.[row.id]) || t("apiKeyPlaceholder")}
                  value={row.key}
                  onChange={(e) => updateCustomRow(index, { key: e.target.value })}
                />
              </label>
              <div className="flex items-center gap-2">
                {hasKey && (
                  <Button size="sm" variant="ghost" onClick={() => void clearKey(row.id)} disabled={busy}>
                    {clearing === row.id ? t("clearing") : t("clearKey")}
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => void deleteCustomRow(index)} disabled={busy}>
                  {t("customProviderDelete")}
                </Button>
              </div>
            </div>
          );
        })}
        <Button size="sm" variant="outline" onClick={addCustomRow} disabled={busy}>
          {t("customProviderAdd")}
        </Button>
      </div>
      <p className="text-[11px] text-zinc-500">{t("byokHint")}</p>
      <p className="text-[11px] text-zinc-500">{t("envFallbackHint")}</p>
      <Button size="sm" onClick={() => void save()} disabled={busy}>
        {saving ? t("saving") : t("saveSettings")}
      </Button>
      {msg && <p className="text-xs text-zinc-400">{msg}</p>}
    </div>
  );
}
