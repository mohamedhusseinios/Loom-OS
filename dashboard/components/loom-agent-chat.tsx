"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Archive, ArchiveRestore, Brain, Check, Copy, Loader2, MessageSquarePlus, Send, Settings, Trash2 } from "lucide-react";
import { ChatMarkdown } from "@/components/chat-markdown";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import {
  agentChatStream,
  archiveAgentChat,
  deleteAgentChat,
  unarchiveAgentChat,
  listAgentChatMessages,
  listAgentChats,
  type AgentChatSummary,
} from "@/lib/api";

interface Msg {
  role: "user" | "assistant";
  content: string;
  reasoning?: string | null;
}

interface LoomAgentChatProps {
  projectId: string;
  taskId?: string | null;
  onSuggestion?: (suggestionId: string) => void;
}

const CHAT_FONT_STEPS = [0.875, 1, 1.125, 1.25, 1.5] as const;
const CHAT_FONT_KEY = "loom-agent-chat-font-scale";

function readChatFontScale(): number {
  if (typeof window === "undefined") return 1;
  try {
    const raw = window.localStorage.getItem(CHAT_FONT_KEY);
    const n = raw ? Number(raw) : 1;
    return CHAT_FONT_STEPS.includes(n as (typeof CHAT_FONT_STEPS)[number]) ? n : 1;
  } catch {
    return 1;
  }
}

function nearestFontStep(scale: number, dir: 1 | -1): number {
  const idx = CHAT_FONT_STEPS.findIndex((s) => s === scale);
  const i = idx < 0 ? CHAT_FONT_STEPS.indexOf(1) : idx;
  return CHAT_FONT_STEPS[Math.min(CHAT_FONT_STEPS.length - 1, Math.max(0, i + dir))] ?? 1;
}

function previewLabel(chat: AgentChatSummary, fallback: string): string {
  const preview = chat.preview.trim();
  if (!preview) return fallback;
  return preview.length > 48 ? `${preview.slice(0, 48)}…` : preview;
}

export function LoomAgentChat({ projectId, taskId, onSuggestion }: LoomAgentChatProps) {
  const t = useTranslations("LoomAgent");
  const [sessions, setSessions] = useState<AgentChatSummary[]>([]);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [chatId, setChatId] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [userDraft, setUserDraft] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [fontScale, setFontScale] = useState(1);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const copyResetTimerRef = useRef<number | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Latest open-thread token. New Chat, another session, or a scope change bumps it
  // so an in-flight list/messages fetch cannot overwrite that newer choice.
  const sessionLoadRef = useRef(0);

  useEffect(() => () => abortRef.current?.abort(), []);

  const abortInFlight = useCallback(() => {
    if (!abortRef.current) return;
    abortRef.current.abort();
    abortRef.current = null;
    setBusy(false);
  }, []);

  useEffect(() => {
    setFontScale(readChatFontScale());
  }, []);

  const commitFontScale = useCallback((next: number | ((prev: number) => number)) => {
    setFontScale((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      try {
        window.localStorage.setItem(CHAT_FONT_KEY, String(value));
      } catch {
        /* private mode / quota */
      }
      return value;
    });
  }, []);

  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (!el!.contains(document.activeElement) && !el!.matches(":hover")) return;
      if (e.key === "=" || e.key === "+") {
        e.preventDefault();
        commitFontScale((prev) => nearestFontStep(prev, 1));
      } else if (e.key === "-") {
        e.preventDefault();
        commitFontScale((prev) => nearestFontStep(prev, -1));
      } else if (e.key === "0") {
        e.preventDefault();
        commitFontScale(1);
      }
    }
    function onWheel(e: WheelEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      e.preventDefault();
      commitFontScale((prev) => nearestFontStep(prev, e.deltaY < 0 ? 1 : -1));
    }
    window.addEventListener("keydown", onKey);
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      window.removeEventListener("keydown", onKey);
      el.removeEventListener("wheel", onWheel);
    };
  }, [commitFontScale]);

  const refreshSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const chats = await listAgentChats(projectId, taskId || undefined, { archived: showArchived });
      setSessions(chats);
      return chats;
    } catch (e) {
      setError(e instanceof Error ? e.message : t("chatError"));
      return [] as AgentChatSummary[];
    } finally {
      setLoadingSessions(false);
    }
  }, [projectId, taskId, showArchived, t]);

  const loadSession = useCallback(async (id: string) => {
    const requestId = ++sessionLoadRef.current;
    abortInFlight();
    setLoadingMessages(true);
    setError("");
    setChatId(id);
    setUserDraft(false);
    try {
      const rows = await listAgentChatMessages(projectId, id);
      if (requestId !== sessionLoadRef.current) return;
      setMessages(
        rows
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            reasoning: m.reasoning_content || null,
          })),
      );
    } catch (e) {
      if (requestId !== sessionLoadRef.current) return;
      setError(e instanceof Error ? e.message : t("chatError"));
      setMessages([]);
    } finally {
      if (requestId === sessionLoadRef.current) setLoadingMessages(false);
    }
  }, [projectId, t, abortInFlight]);

  async function copyText(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return;
    }
    setCopiedKey(key);
    if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
    copyResetTimerRef.current = window.setTimeout(() => {
      setCopiedKey((k) => (k === key ? null : k));
      copyResetTimerRef.current = null;
    }, 1500);
  }

  function startNewChat() {
    sessionLoadRef.current += 1;
    abortInFlight();
    setChatId(undefined);
    setMessages([]);
    setInput("");
    setError("");
    setLoadingMessages(false);
    setUserDraft(true);
  }

  function clearOpenChat() {
    sessionLoadRef.current += 1;
    abortInFlight();
    setChatId(undefined);
    setMessages([]);
    setLoadingMessages(false);
    setUserDraft(true);
  }

  async function onArchive(id: string) {
    try {
      await archiveAgentChat(projectId, id);
      if (chatId === id) clearOpenChat();
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function onUnarchive(id: string) {
    try {
      await unarchiveAgentChat(projectId, id);
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function onConfirmDelete() {
    if (!pendingDeleteId) return;
    const id = pendingDeleteId;
    setPendingDeleteId(null);
    try {
      await deleteAgentChat(projectId, id);
      if (chatId === id) clearOpenChat();
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    let cancelled = false;
    const requestId = ++sessionLoadRef.current;
    abortInFlight();
    setInput("");
    setError("");
    setChatId(undefined);
    setMessages([]);
    setLoadingMessages(false);
    setPendingDeleteId(null);
    setUserDraft(false);
    (async () => {
      const chats = await refreshSessions();
      if (cancelled || requestId !== sessionLoadRef.current) return;
      if (showArchived || chats.length === 0) {
        if (!showArchived && chats.length === 0) setUserDraft(true);
        return;
      }
      await loadSession(chats[0].id);
    })();
    return () => {
      cancelled = true;
      sessionLoadRef.current += 1;
    };
  }, [projectId, taskId, showArchived, refreshSessions, loadSession, abortInFlight]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError("");
    setMessages((m) => [...m, { role: "user", content: text }, { role: "assistant", content: "", reasoning: null }]);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const live = () => !controller.signal.aborted;
    const patchLast = (fn: (last: Msg) => Msg) => {
      if (!live()) return;
      setMessages((rows) => {
        const last = rows[rows.length - 1];
        if (last?.role !== "assistant") return rows;
        return [...rows.slice(0, -1), fn(last)];
      });
    };
    const dropEmptyAssistant = () => {
      setMessages((rows) => {
        const last = rows[rows.length - 1];
        return last?.role === "assistant" && !last.content && !last.reasoning ? rows.slice(0, -1) : rows;
      });
    };
    try {
      await agentChatStream(
        projectId,
        { message: text, task_id: taskId || undefined, chat_id: chatId },
        {
          onMeta: (id) => {
            if (live()) setChatId(id);
          },
          onReasoningDelta: (chunk) => patchLast((last) => ({ ...last, reasoning: (last.reasoning || "") + chunk })),
          onContentDelta: (chunk) => patchLast((last) => ({ ...last, content: last.content + chunk })),
          onDone: (result) => {
            if (!live()) return;
            setChatId(result.chat_id);
            patchLast((last) => ({
              role: "assistant",
              content: result.reply || last.content,
              reasoning: result.reasoning ?? last.reasoning,
            }));
            if (!result.reply && !result.reasoning) setError(t("emptyReply"));
            if (result.suggestion_id && onSuggestion) onSuggestion(result.suggestion_id);
          },
          onError: (message) => {
            if (live()) setError(message);
          },
        },
        controller.signal,
      );
      if (live()) await refreshSessions();
    } catch (e) {
      if (live()) setError(e instanceof Error ? e.message : t("chatError"));
    } finally {
      if (live()) dropEmptyAssistant();
      if (abortRef.current === controller) {
        abortRef.current = null;
        setBusy(false);
      }
    }
  }

  const activeSession = sessions.find((s) => s.id === chatId);
  const drafting = !chatId;

  return (
    <div
      ref={panelRef}
      tabIndex={0}
      style={{ ["--chat-font-scale" as string]: String(fontScale) }}
      className="relative flex h-full min-h-[280px] overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/60 outline-none [&_.chat-md-root[data-variant=default]]:text-[length:calc(0.875rem*var(--chat-font-scale))] [&_.chat-md-root[data-variant=muted]]:text-[length:calc(0.75rem*var(--chat-font-scale))] [&_.chat-md-root[data-variant=compact]]:text-[length:calc(0.6875rem*var(--chat-font-scale))]"
    >
      <aside className="flex w-[12.5rem] shrink-0 flex-col border-e border-zinc-800" aria-label={t("sessions")}>
        <div className="flex items-center justify-between gap-1 border-b border-zinc-800 px-2 py-2">
          <span className="text-[11px] font-medium text-zinc-400">
            {t("sessions")}
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0 text-zinc-400 hover:text-zinc-100"
            onClick={startNewChat}
            title={t("newChat")}
            aria-label={t("newChat")}
            aria-pressed={drafting}
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div
          className="grid grid-cols-2 gap-0.5 border-b border-zinc-800 p-1"
          role="tablist"
          aria-label={t("sessionLists")}
        >
          <button
            type="button"
            role="tab"
            aria-selected={!showArchived}
            className={`rounded px-1.5 py-1 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 ${
              !showArchived ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            }`}
            onClick={() => setShowArchived(false)}
          >
            {t("activeSessions")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={showArchived}
            className={`rounded px-1.5 py-1 text-[10px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 ${
              showArchived ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            }`}
            onClick={() => setShowArchived(true)}
          >
            {t("archivedSessions")}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
          {userDraft && drafting && !showArchived && (
            <div
              className="rounded-md border border-dashed border-zinc-700 bg-zinc-900/40 px-2 py-1.5 text-[11px] text-zinc-300"
              aria-current="true"
            >
              {t("draftSession")}
            </div>
          )}
          {loadingSessions && sessions.length === 0 && (
            <p className="px-1.5 py-1 text-[11px] text-zinc-500">{t("loadingSessions")}</p>
          )}
          {!loadingSessions && sessions.length === 0 && (
            <div className="px-1.5 py-2 space-y-1">
              <p className="text-[11px] text-zinc-400">
                {showArchived ? t("noArchivedSessions") : t("noSessions")}
              </p>
              {!showArchived && (
                <p className="text-[10px] text-zinc-600 leading-snug">{t("noSessionsHint")}</p>
              )}
            </div>
          )}
          {sessions.map((s) => {
            const active = s.id === chatId;
            return (
              <div key={s.id} className="group/row relative">
                <button
                  type="button"
                  onClick={() => void loadSession(s.id)}
                  aria-current={active ? "true" : undefined}
                  className={`w-full rounded-md px-2 py-1.5 text-start text-[11px] leading-snug transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 ${
                    active
                      ? "bg-zinc-800 text-zinc-100 ring-1 ring-zinc-600"
                      : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                  }`}
                >
                  <span className="line-clamp-2 pe-12 [&_.chat-md-root_p]:my-0">
                    <ChatMarkdown content={previewLabel(s, t("untitledSession"))} variant="compact" />
                  </span>
                </button>
                <div className="pointer-events-none absolute end-1 top-1 flex gap-0.5 opacity-0 transition-opacity group-hover/row:pointer-events-auto group-hover/row:opacity-100 group-focus-within/row:pointer-events-auto group-focus-within/row:opacity-100 [@media(pointer:coarse)]:pointer-events-auto [@media(pointer:coarse)]:opacity-100">
                  {showArchived ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-5 w-5 p-0 text-zinc-500 hover:text-zinc-100"
                      title={t("unarchiveSession")}
                      aria-label={t("unarchiveSession")}
                      onClick={(e) => {
                        e.stopPropagation();
                        void onUnarchive(s.id);
                      }}
                    >
                      <ArchiveRestore className="h-3 w-3" />
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-5 w-5 p-0 text-zinc-500 hover:text-zinc-100"
                      title={t("archiveSession")}
                      aria-label={t("archiveSession")}
                      onClick={(e) => {
                        e.stopPropagation();
                        void onArchive(s.id);
                      }}
                    >
                      <Archive className="h-3 w-3" />
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-5 w-5 p-0 text-zinc-500 hover:text-red-400"
                    title={t("deleteSession")}
                    aria-label={t("deleteSession")}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPendingDeleteId(s.id);
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-zinc-100 truncate">
              {drafting
                ? t("newChat")
                : activeSession
                  ? previewLabel(activeSession, t("untitledSession"))
                  : t("untitledSession")}
            </h3>
            <p className="text-[11px] text-zinc-500">
              {taskId ? t("taskScoped") : t("projectScoped")}
              {busy ? ` · ${t("streaming")}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-0.5">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 px-1.5 text-[11px]"
              onClick={() => commitFontScale((prev) => nearestFontStep(prev, -1))}
              title={t("zoomOut")}
              aria-label={t("zoomOut")}
            >
              A−
            </Button>
            <span
              className="min-w-[2.5rem] text-center text-[10px] text-zinc-500"
              title={t("zoomReset")}
              onDoubleClick={() => commitFontScale(1)}
              role="presentation"
            >
              {t("zoomPercent", { pct: Math.round(fontScale * 100) })}
            </span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 px-1.5 text-[11px]"
              onClick={() => commitFontScale((prev) => nearestFontStep(prev, 1))}
              title={t("zoomIn")}
              aria-label={t("zoomIn")}
            >
              A+
            </Button>
            <Link
              href="/agent-settings"
              className="inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-[0.8rem] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            >
              <Settings className="w-3.5 h-3.5" />
              {t("settings")}
            </Link>
          </div>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto p-3">
          {loadingMessages && (
            <p className="text-xs text-zinc-500">{t("loadingMessages")}</p>
          )}
          {!loadingMessages && messages.length === 0 && !busy && (
            <div className="rounded-md border border-zinc-800/80 bg-zinc-900/30 px-3 py-3 space-y-1.5 max-w-prose">
              <p className="text-xs text-zinc-300">{t("emptyHint")}</p>
              <p className="text-[11px] text-zinc-500 leading-snug">{t("emptyHintDetail")}</p>
            </div>
          )}
          {messages.map((m, i) => (
            m.role === "assistant" && !m.content && !m.reasoning ? null : <div
              key={i}
              className={`rounded-md px-2.5 py-2 text-sm [font-size:calc(0.875rem*var(--chat-font-scale))] ${
                m.role === "user"
                  ? "ms-8 bg-zinc-800 text-zinc-100"
                  : "me-8 bg-zinc-900 text-zinc-300"
              }`}
            >
              {m.role === "assistant" && (m.content || m.reasoning) ? (
                <div className="mb-1 flex items-center justify-end gap-0.5">
                  {m.reasoning ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-6 gap-1 px-1.5 text-[10px] text-zinc-500 hover:text-zinc-100"
                      title={copiedKey === `${i}:thinking` ? t("copied") : t("copyThinking")}
                      aria-label={copiedKey === `${i}:thinking` ? t("copied") : t("copyThinking")}
                      onClick={() => void copyText(m.reasoning || "", `${i}:thinking`)}
                    >
                      {copiedKey === `${i}:thinking` ? <Check className="h-3 w-3" /> : <Brain className="h-3 w-3" />}
                      {copiedKey === `${i}:thinking` ? t("copied") : null}
                    </Button>
                  ) : null}
                  {m.content ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-6 gap-1 px-1.5 text-[10px] text-zinc-500 hover:text-zinc-100"
                      title={copiedKey === `${i}:message` ? t("copied") : t("copyMessage")}
                      aria-label={copiedKey === `${i}:message` ? t("copied") : t("copyMessage")}
                      onClick={() => void copyText(m.content, `${i}:message`)}
                    >
                      {copiedKey === `${i}:message` ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      {copiedKey === `${i}:message` ? t("copied") : null}
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {m.role === "assistant" && m.reasoning ? (
                <details className="group/think mb-2 rounded border border-zinc-800 bg-zinc-950/70 open:bg-zinc-950/90">
                  <summary className="cursor-pointer select-none list-none px-2 py-1.5 text-[11px] font-medium text-zinc-400 marker:content-none [&::-webkit-details-marker]:hidden">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="inline-block text-zinc-500 transition-transform group-open/think:rotate-90">▸</span>
                      {t("thinkingLabel")}
                    </span>
                  </summary>
                  <div className="border-t border-zinc-800 px-2.5 py-2">
                    <ChatMarkdown
                      content={m.reasoning || ""}
                      variant="muted"
                      copyCodeLabel={t("copyCode")}
                      copiedLabel={t("copied")}
                    />
                  </div>
                </details>
              ) : null}
              {m.content ? (
                <ChatMarkdown content={m.content} copyCodeLabel={t("copyCode")} copiedLabel={t("copied")} />
              ) : m.reasoning ? (
                <p className="text-xs text-zinc-500">{t("reasoningOnlyHint")}</p>
              ) : null}
            </div>
          ))}
          {busy && !(messages[messages.length - 1]?.role === "assistant" && (messages[messages.length - 1].content || messages[messages.length - 1].reasoning)) && (
            <div className="me-8 flex items-center gap-2 rounded-md bg-zinc-900 px-2.5 py-2 text-sm text-zinc-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("thinking")}
            </div>
          )}
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
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
      {pendingDeleteId && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-zinc-950/80 p-4">
          <div
            role="alertdialog"
            aria-labelledby="delete-session-title"
            className="w-full max-w-xs rounded-lg border border-zinc-700 bg-zinc-900 p-4 shadow-lg"
          >
            <h4 id="delete-session-title" className="text-sm font-semibold text-zinc-100">
              {t("deleteSessionConfirmTitle")}
            </h4>
            <p className="mt-1 text-xs text-zinc-400">{t("deleteSessionConfirmBody")}</p>
            <div className="mt-3 flex justify-end gap-2">
              <Button type="button" size="sm" variant="ghost" onClick={() => setPendingDeleteId(null)}>
                {t("cancel")}
              </Button>
              <Button type="button" size="sm" variant="destructive" onClick={() => void onConfirmDelete()}>
                {t("confirmDelete")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
