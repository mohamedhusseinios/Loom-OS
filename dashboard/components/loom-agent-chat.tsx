"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { agentChat } from "@/lib/api";
import { AgentSettingsPanel } from "@/components/agent-settings-panel";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

interface LoomAgentChatProps {
  projectId: string;
  taskId?: string | null;
  onSuggestion?: (suggestionId: string) => void;
}

export function LoomAgentChat({ projectId, taskId, onSuggestion }: LoomAgentChatProps) {
  const t = useTranslations("LoomAgent");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [chatId, setChatId] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await agentChat(projectId, {
        message: text,
        task_id: taskId || undefined,
        chat_id: chatId,
      });
      setChatId(res.chat_id);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
      if (res.suggestion_id && onSuggestion) onSuggestion(res.suggestion_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("chatError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full min-h-[280px] rounded-lg border border-zinc-800 bg-zinc-950/60">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">{t("title")}</h3>
          <p className="text-[11px] text-zinc-500">
            {taskId ? t("taskScoped") : t("projectScoped")}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setShowSettings((s) => !s)}>
          {t("settings")}
        </Button>
      </div>
      {showSettings && (
        <div className="p-3 border-b border-zinc-800">
          <AgentSettingsPanel />
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {messages.length === 0 && (
          <p className="text-xs text-zinc-500">{t("emptyHint")}</p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`text-sm rounded-md px-2.5 py-2 whitespace-pre-wrap ${
              m.role === "user"
                ? "bg-zinc-800 text-zinc-100 ms-8"
                : "bg-zinc-900 text-zinc-300 me-8"
            }`}
          >
            {m.content}
          </div>
        ))}
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
      <div className="flex gap-2 border-t border-zinc-800 p-2">
        <input
          className="flex-1 rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
          placeholder={t("placeholder")}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={busy}
        />
        <Button size="sm" onClick={() => void send()} disabled={busy || !input.trim()}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </Button>
      </div>
    </div>
  );
}
