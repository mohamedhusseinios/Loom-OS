# Agent Chat Markdown, Zoom & Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Loom Agent chat readable (GFM + highlighted code), zoomable, copyable, and truly streaming for project-scoped replies — including Markdown in thinking, sidebar previews, and suggestion prose.

**Architecture:** Shared client `ChatMarkdown` component styles all Markdown surfaces. Chat panel owns a CSS `--chat-font-scale` with header + shortcut controls. Daemon gains `chat_stream` on LLM clients and `POST .../agent/chat/stream` (SSE). Dashboard consumes the stream into a live assistant bubble. Task-scoped chats keep orchestrator behavior and emit a one-shot stream (`meta` → full `content_delta` → `done`) so the UI path stays unified.

**Tech Stack:** Next.js 16 + React 19 (`dashboard/`), `react-markdown` + `remark-gfm` + `rehype-pretty-code` + `shiki` (fallback: `rehype-highlight` if client bundling fails), FastAPI SSE (`StreamingResponse`), existing `daemon/llm_client.py` urllib HTTP, pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-agent-chat-markdown-zoom-stream-design.md`

## Global Constraints

- Markdown everywhere: user, assistant, thinking, sidebar preview, suggestion `prose` — no `rehype-raw`
- Font zoom: header `A−`/`A+` **and** Ctrl/Cmd ±/0 + Ctrl/Cmd+wheel; persist `localStorage` key `loom-agent-chat-font-scale`; steps `0.875 | 1 | 1.125 | 1.25 | 1.5`
- Keep non-streaming `POST /api/projects/{id}/agent/chat` unchanged for tests/compat
- New stream endpoint: SSE `text/event-stream` with events `meta`, `reasoning_delta`, `content_delta`, `done`, `error`
- Project chat (`task_id` null): real token stream from LLM
- Task chat (`task_id` set): one-shot via existing orchestrator path, still through stream endpoint
- On stream failure after partial text: persist partial assistant message when any content/reasoning was received; emit terminal `error` event
- Every new UI string in both `dashboard/messages/en.json` and `dashboard/messages/ar.json` under `LoomAgent`
- Preserve zinc dark chat chrome; no purple/glow redesign
- Filesystem inbox + single-process daemon unchanged
- Do not push / open / merge without explicit user approval
- Keep existing pytest suite green; add LLM stream + API stream tests

## File map

| Path | Responsibility |
|------|----------------|
| `dashboard/package.json` | Markdown + highlighter deps |
| `dashboard/components/chat-markdown.tsx` | Shared GFM + code renderer |
| `dashboard/components/loom-agent-chat.tsx` | Bubbles, zoom, copy, stream send, sidebar preview |
| `dashboard/components/suggestion-chip.tsx` | Markdown prose |
| `dashboard/lib/api.ts` | `agentChatStream` + types |
| `dashboard/messages/en.json` / `ar.json` | Zoom / copy / stream strings |
| `daemon/llm_client.py` | `StreamDelta`, `chat_stream` on OpenAI + Anthropic clients |
| `daemon/agent_runtime.py` | `chat_stream` async generator |
| `daemon/api.py` | `POST .../agent/chat/stream` SSE |
| `tests/test_llm_clients_providers.py` | Stream parsing unit tests |
| `tests/test_agent_api.py` | Stream endpoint HTTP tests |

## Phasing note

Tasks 1–5 deliver readable/zoomable/copyable chat against the existing non-stream API (shippable alone). Tasks 6–9 add streaming. Prefer two PRs if review load is high; one branch is fine if the user wants everything together.

---

### Task 1: `ChatMarkdown` component + dependencies

**Files:**
- Modify: `dashboard/package.json` (via `npm install`)
- Create: `dashboard/components/chat-markdown.tsx`
- Test: manual render in a throwaway page **or** verify `npm run lint` after Task 2 wires it (no Jest suite in dashboard)

**Interfaces:**
- Consumes: none
- Produces:
  - `export function ChatMarkdown(props: { content: string; className?: string; variant?: "default" | "muted" | "compact" }): JSX.Element | null`
  - Renders GFM; fenced code highlighted; returns `null` when `content.trim()` is empty

- [ ] **Step 1: Install dependencies**

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os/dashboard
npm install react-markdown remark-gfm rehype-pretty-code shiki
```

If `rehype-pretty-code` fails to bundle under Next 16 client components, uninstall it and install `rehype-highlight` + `highlight.js` instead, then adapt Step 3 to use `rehypePlugins={[rehypeHighlight]}` and import a dark highlight.js CSS in the component (or scoped classes). Document the fallback in the commit message.

- [ ] **Step 2: Create `chat-markdown.tsx`**

```tsx
"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypePrettyCode from "rehype-pretty-code";
import { cn } from "@/lib/utils";

type Variant = "default" | "muted" | "compact";

const variantClass: Record<Variant, string> = {
  default: "chat-md text-sm text-zinc-200",
  muted: "chat-md text-xs leading-relaxed text-zinc-500",
  compact: "chat-md text-[11px] leading-snug text-zinc-400",
};

export function ChatMarkdown(props: { content: string; className?: string; variant?: Variant }) {
  const { content, className, variant = "default" } = props;
  if (!content.trim()) return null;
  return (
    <div className={cn(variantClass[variant], "chat-md-root break-words", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypePrettyCode, { theme: "github-dark", keepBackground: false }]]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-sky-400 underline underline-offset-2">
              {children}
            </a>
          ),
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded-md border border-zinc-800 bg-zinc-950/80 p-2 text-[0.85em]">
              {children}
            </pre>
          ),
          code: ({ className: codeClass, children, ...rest }) => {
            const isBlock = Boolean(codeClass);
            if (isBlock) {
              return (
                <code className={cn(codeClass, "font-mono")} {...rest}>
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[0.9em] text-zinc-100" {...rest}>
                {children}
              </code>
            );
          },
          ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 ps-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 ps-5">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          h1: ({ children }) => <h1 className="mb-1 mt-2 text-base font-semibold text-zinc-50">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-1 mt-2 text-sm font-semibold text-zinc-50">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-medium text-zinc-100">{children}</h3>,
          p: ({ children }) => <p className="my-1.5 leading-relaxed">{children}</p>,
          blockquote: ({ children }) => (
            <blockquote className="my-1.5 border-s-2 border-zinc-600 ps-2 text-zinc-400">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-left text-[0.9em]">{children}</table>
            </div>
          ),
          th: ({ children }) => <th className="border border-zinc-700 bg-zinc-900 px-2 py-1 font-medium">{children}</th>,
          td: ({ children }) => <td className="border border-zinc-800 px-2 py-1">{children}</td>,
          hr: () => <hr className="my-2 border-zinc-800" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
```

Confirm `@/lib/utils` exports `cn` (it does in this dashboard). If not, use `clsx` / `tailwind-merge` inline the same way other components do.

- [ ] **Step 3: Lint check**

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os/dashboard
npm run lint
```

Expected: PASS (or only pre-existing unrelated warnings).

- [ ] **Step 4: Commit**

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os
git add dashboard/package.json dashboard/package-lock.json dashboard/components/chat-markdown.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): add ChatMarkdown for GFM agent replies

EOF
)"
```

---

### Task 2: Wire Markdown into chat bubbles (user / assistant / thinking)

**Files:**
- Modify: `dashboard/components/loom-agent-chat.tsx` (message map ~303–329)
- Test: manual in browser against running daemon; `npm run lint`

**Interfaces:**
- Consumes: `ChatMarkdown` from Task 1
- Produces: bubbles render Markdown instead of `whitespace-pre-wrap` text

- [ ] **Step 1: Import and replace content renderers**

In `loom-agent-chat.tsx`:

```tsx
import { ChatMarkdown } from "@/components/chat-markdown";
```

Replace the thinking body:

```tsx
<div className="border-t border-zinc-800 px-2.5 py-2">
  <ChatMarkdown content={m.reasoning || ""} variant="muted" />
</div>
```

Replace the main content:

```tsx
{m.content ? (
  <ChatMarkdown content={m.content} />
) : m.reasoning ? (
  <p className="text-xs text-zinc-500">{t("reasoningOnlyHint")}</p>
) : null}
```

Remove `whitespace-pre-wrap` wrappers for those two paths.

- [ ] **Step 2: Lint**

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os/dashboard && npm run lint
```

Expected: PASS.

- [ ] **Step 3: Manual check**

With daemon + `npm run dev`, open Agent chat, load a reply containing `##`, `**bold**`, lists, and `` `code` `` — confirm formatted output.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/loom-agent-chat.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): render agent chat bubbles as Markdown

EOF
)"
```

---

### Task 3: Chat font zoom (header + shortcuts + persistence)

**Files:**
- Modify: `dashboard/components/loom-agent-chat.tsx`
- Modify: `dashboard/messages/en.json`, `dashboard/messages/ar.json`
- Test: manual zoom + reload persistence

**Interfaces:**
- Consumes: none from prior tasks beyond chat root DOM
- Produces:
  - `CHAT_FONT_STEPS = [0.875, 1, 1.125, 1.25, 1.5]`
  - `localStorage` key `loom-agent-chat-font-scale`
  - CSS var `--chat-font-scale` on chat panel root

- [ ] **Step 1: Add i18n keys**

In both locale files under `LoomAgent`, add:

```json
"zoomIn": "Larger text",
"zoomOut": "Smaller text",
"zoomReset": "Reset text size",
"zoomPercent": "{pct}%"
```

Arabic (acceptable concise):

```json
"zoomIn": "تكبير النص",
"zoomOut": "تصغير النص",
"zoomReset": "إعادة حجم النص",
"zoomPercent": "{pct}%"
```

- [ ] **Step 2: Add zoom state + handlers in `LoomAgentChat`**

Near top of file (module scope):

```tsx
const CHAT_FONT_STEPS = [0.875, 1, 1.125, 1.25, 1.5] as const;
const CHAT_FONT_KEY = "loom-agent-chat-font-scale";

function readChatFontScale(): number {
  if (typeof window === "undefined") return 1;
  const raw = window.localStorage.getItem(CHAT_FONT_KEY);
  const n = raw ? Number(raw) : 1;
  return CHAT_FONT_STEPS.includes(n as (typeof CHAT_FONT_STEPS)[number]) ? n : 1;
}

function nearestFontStep(scale: number, dir: 1 | -1): number {
  const idx = CHAT_FONT_STEPS.findIndex((s) => s === scale);
  const i = idx < 0 ? CHAT_FONT_STEPS.indexOf(1) : idx;
  return CHAT_FONT_STEPS[Math.min(CHAT_FONT_STEPS.length - 1, Math.max(0, i + dir))] ?? 1;
}
```

Inside the component:

```tsx
const [fontScale, setFontScale] = useState(1);
const panelRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  setFontScale(readChatFontScale());
}, []);

function commitFontScale(next: number) {
  setFontScale(next);
  window.localStorage.setItem(CHAT_FONT_KEY, String(next));
}
```

On the outermost chat panel `div`, add `ref={panelRef}`, `tabIndex={0}`, and:

```tsx
style={{ ["--chat-font-scale" as string]: String(fontScale) }}
className="... [&_.chat-md-root]:text-[length:calc(1em*var(--chat-font-scale))]"
```

Also scale bubble base text:

```tsx
className={`rounded-md px-2.5 py-2 text-sm [font-size:calc(0.875rem*var(--chat-font-scale))] ...`}
```

Header controls (next to Settings `Link`):

```tsx
<div className="flex items-center gap-0.5">
  <Button type="button" size="sm" variant="ghost" className="h-7 px-1.5 text-[11px]"
    onClick={() => commitFontScale(nearestFontStep(fontScale, -1))}
    title={t("zoomOut")} aria-label={t("zoomOut")}>A−</Button>
  <span className="min-w-[2.5rem] text-center text-[10px] text-zinc-500" title={t("zoomReset")}
    onDoubleClick={() => commitFontScale(1)} role="presentation">
    {t("zoomPercent", { pct: Math.round(fontScale * 100) })}
  </span>
  <Button type="button" size="sm" variant="ghost" className="h-7 px-1.5 text-[11px]"
    onClick={() => commitFontScale(nearestFontStep(fontScale, 1))}
    title={t("zoomIn")} aria-label={t("zoomIn")}>A+</Button>
  {/* existing Settings Link */}
</div>
```

Keyboard + wheel (attach on panel):

```tsx
useEffect(() => {
  const el = panelRef.current;
  if (!el) return;
  function onKey(e: KeyboardEvent) {
    if (!(e.metaKey || e.ctrlKey)) return;
    if (!el.contains(document.activeElement) && document.activeElement !== el) {
      // allow when pointer is over panel
      if (!el.matches(":hover")) return;
    }
    if (e.key === "=" || e.key === "+") {
      e.preventDefault();
      commitFontScale(nearestFontStep(fontScale, 1));
    } else if (e.key === "-") {
      e.preventDefault();
      commitFontScale(nearestFontStep(fontScale, -1));
    } else if (e.key === "0") {
      e.preventDefault();
      commitFontScale(1);
    }
  }
  function onWheel(e: WheelEvent) {
    if (!(e.metaKey || e.ctrlKey)) return;
    e.preventDefault();
    commitFontScale(nearestFontStep(fontScale, e.deltaY < 0 ? 1 : -1));
  }
  window.addEventListener("keydown", onKey);
  el.addEventListener("wheel", onWheel, { passive: false });
  return () => {
    window.removeEventListener("keydown", onKey);
    el.removeEventListener("wheel", onWheel);
  };
}, [fontScale]);
```

Fix stale closure by using functional updates if needed:

```tsx
setFontScale((prev) => {
  const next = nearestFontStep(prev, dir);
  window.localStorage.setItem(CHAT_FONT_KEY, String(next));
  return next;
});
```

- [ ] **Step 3: Manual verify**

Zoom in/out via buttons, Cmd/Ctrl+wheel, reload page — scale persists.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/loom-agent-chat.tsx dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "$(cat <<'EOF'
feat(dashboard): add persisted chat font zoom controls

EOF
)"
```

---

### Task 4: Copy message / thinking / code

**Files:**
- Modify: `dashboard/components/chat-markdown.tsx` (code-block copy)
- Modify: `dashboard/components/loom-agent-chat.tsx` (bubble copy)
- Modify: `dashboard/messages/en.json`, `ar.json`
- Test: manual clipboard

**Interfaces:**
- Consumes: `ChatMarkdown`; `navigator.clipboard.writeText`
- Produces: copy buttons with brief “Copied” feedback

- [ ] **Step 1: i18n**

```json
"copyMessage": "Copy message",
"copyThinking": "Copy thinking",
"copyCode": "Copy code",
"copied": "Copied"
```

Arabic:

```json
"copyMessage": "نسخ الرسالة",
"copyThinking": "نسخ التفكير",
"copyCode": "نسخ الشيفرة",
"copied": "تم النسخ"
```

- [ ] **Step 2: Code-block copy inside `ChatMarkdown`**

Wrap `pre` component with a relative container and a small button that copies `String(children)` text (walk text from children or use a ref on `<pre>`). Show `t`-less English only if ChatMarkdown has no i18n — prefer passing optional `copyLabel` / `copiedLabel` props:

```tsx
export function ChatMarkdown(props: {
  content: string;
  className?: string;
  variant?: Variant;
  copyCodeLabel?: string;
  copiedLabel?: string;
}) { ... }
```

- [ ] **Step 3: Bubble-level copy in `loom-agent-chat.tsx`**

For assistant bubbles, add a top-end row of ghost icon buttons (`Copy` from lucide):

```tsx
async function copyText(text: string, key: string) {
  await navigator.clipboard.writeText(text);
  setCopiedKey(key);
  window.setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1500);
}
```

Show Copy message when `m.content`; Copy thinking when `m.reasoning`.

- [ ] **Step 4: Manual verify + lint + commit**

```bash
cd dashboard && npm run lint
git add dashboard/components/chat-markdown.tsx dashboard/components/loom-agent-chat.tsx dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "$(cat <<'EOF'
feat(dashboard): add copy actions for chat Markdown

EOF
)"
```

---

### Task 5: Sidebar preview Markdown + suggestion prose

**Files:**
- Modify: `dashboard/components/loom-agent-chat.tsx` (`previewLabel` / session row)
- Modify: `dashboard/components/suggestion-chip.tsx`
- Test: visual — session list no longer shows raw `##` / `**`; suggestion chip formats lists

**Interfaces:**
- Consumes: `ChatMarkdown` variants `compact` / `muted`
- Produces: clamped Markdown preview; Markdown suggestion prose

- [ ] **Step 1: Session row preview**

Replace plain `previewLabel` text span content with:

```tsx
<span className="line-clamp-2 pe-12 [&_.chat-md-root_p]:my-0">
  <ChatMarkdown content={previewLabel(s, t("untitledSession"))} variant="compact" />
</span>
```

Keep `previewLabel` truncation helper (char slice) so Markdown source stays short.

- [ ] **Step 2: Suggestion chip**

In `suggestion-chip.tsx`:

```tsx
import { ChatMarkdown } from "@/components/chat-markdown";
// ...
<ChatMarkdown content={suggestion.prose} variant="muted" className="mt-1" />
```

Remove `whitespace-pre-wrap` on that paragraph.

- [ ] **Step 3: Lint + commit**

```bash
cd dashboard && npm run lint
git add dashboard/components/loom-agent-chat.tsx dashboard/components/suggestion-chip.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): Markdown for session previews and suggestions

EOF
)"
```

---

### Task 6: LLM `StreamDelta` + OpenAI-compatible `chat_stream`

**Files:**
- Modify: `daemon/llm_client.py`
- Test: `tests/test_llm_clients_providers.py`

**Interfaces:**
- Consumes: existing `_open_http`, `resolve_chat_completions_url`, distill helpers
- Produces:
  - `@dataclass class StreamDelta: kind: Literal["reasoning", "content"]; text: str`
  - `LlmClientProtocol.chat_stream(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> Iterator[StreamDelta]`
  - `LlmClient.chat_stream(...)` yielding deltas; sets `last_reasoning_content` / `last_usage` when stream ends
  - After stream, if content empty but reasoning present, call `_distill_final_reply` and yield one final `content` delta (same contract as `chat()`)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_clients_providers.py`:

```python
def test_openai_chat_stream_yields_content_deltas(monkeypatch):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    class _StreamResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise AssertionError("stream should iterate lines, not read()")

        def __iter__(self):
            return iter(chunks)

    def fake_open(req, timeout=120.0):
        body = json.loads(req.data.decode())
        assert body["stream"] is True
        return _StreamResp()

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    client = LlmClient(api_key="sk-test")
    events = list(client.chat_stream([{"role": "user", "content": "hi"}], model="m"))
    texts = [(e.kind, e.text) for e in events]
    assert ("content", "Hel") in texts
    assert ("content", "lo") in texts
    assert ("reasoning", "think") in texts
    assert client.last_reasoning_content == "think"
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os
PYTHONPATH=. python -m pytest tests/test_llm_clients_providers.py::test_openai_chat_stream_yields_content_deltas -v
```

Expected: FAIL (`chat_stream` missing).

- [ ] **Step 3: Implement**

In `daemon/llm_client.py`:

```python
from dataclasses import dataclass
from typing import Iterator, Literal

@dataclass(frozen=True)
class StreamDelta:
    kind: Literal["reasoning", "content"]
    text: str
```

Add `chat_stream` to the Protocol.

Implement on `LlmClient`:

- POST body includes `"stream": True`
- Iterate response lines; parse `data: {json}`; skip `[DONE]`
- From each choice delta, yield `StreamDelta("content", ...)` / `StreamDelta("reasoning", ...)` for non-empty fragments
- Accumulate full content + reasoning; apply the same CoT → distill rules as `chat()` at end (if final user-facing content empty and reasoning present, distill and yield `StreamDelta("content", distilled)`)
- Parse usage from final chunk if present

Helper `_iter_sse_json(resp) -> Iterator[dict]` keeps parsing DRY for Anthropic later.

- [ ] **Step 4: Run test — expect PASS**

```bash
PYTHONPATH=. python -m pytest tests/test_llm_clients_providers.py::test_openai_chat_stream_yields_content_deltas -v
```

- [ ] **Step 5: Commit**

```bash
git add daemon/llm_client.py tests/test_llm_clients_providers.py
git commit -m "$(cat <<'EOF'
feat(daemon): stream OpenAI-compatible chat completions

EOF
)"
```

---

### Task 7: Anthropic `chat_stream`

**Files:**
- Modify: `daemon/llm_client.py` (`AnthropicLlmClient`)
- Test: `tests/test_llm_clients_providers.py`

**Interfaces:**
- Consumes: `StreamDelta`, `_split_system_messages`
- Produces: `AnthropicLlmClient.chat_stream(...) -> Iterator[StreamDelta]` using Anthropic SSE (`content_block_delta` / `text_delta`)

- [ ] **Step 1: Failing test**

```python
def test_anthropic_chat_stream_yields_text_deltas(monkeypatch):
    chunks = [
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n',
        b'data: {"type":"message_stop"}\n\n',
    ]

    class _StreamResp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def __iter__(self):
            return iter(chunks)

    def fake_open(req, timeout=120.0):
        body = json.loads(req.data.decode())
        assert body["stream"] is True
        return _StreamResp()

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    client = AnthropicLlmClient(api_key="sk-ant")
    events = list(client.chat_stream([{"role": "user", "content": "x"}], model="claude-sonnet-4-5"))
    assert [(e.kind, e.text) for e in events] == [("content", "Hi")]
```

- [ ] **Step 2: Run — FAIL; implement; PASS; commit**

```bash
PYTHONPATH=. python -m pytest tests/test_llm_clients_providers.py::test_anthropic_chat_stream_yields_text_deltas -v
```

Implementation notes:

- Body: same as `chat()` plus `"stream": True`
- Yield on `content_block_delta` with `delta.type == "text_delta"`
- Anthropic typically has no separate reasoning_content field here — leave `last_reasoning_content` as `None` unless a future provider field appears

```bash
git add daemon/llm_client.py tests/test_llm_clients_providers.py
git commit -m "$(cat <<'EOF'
feat(daemon): stream Anthropic Messages API replies

EOF
)"
```

---

### Task 8: `AgentRuntime.chat_stream` + SSE API route

**Files:**
- Modify: `daemon/agent_runtime.py`
- Modify: `daemon/api.py`
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Consumes: `llm.chat_stream`, existing chat setup (create chat, persist user msg, history)
- Produces:
  - `async def chat_stream(self, project_id: str, project_path: str, payload: AgentChatRequest) -> AsyncIterator[dict]`
  - Yields dicts: `{"event": "meta"|"reasoning_delta"|"content_delta"|"done"|"error", ...}`
  - `POST /api/projects/{project_id}/agent/chat/stream` → `StreamingResponse` SSE

**Event shapes:**

```python
{"event": "meta", "chat_id": str}
{"event": "reasoning_delta", "text": str}
{"event": "content_delta", "text": str}
{"event": "done", "chat_id": str, "reply": str, "reasoning": str | None, "suggestion_id": str | None}
{"event": "error", "message": str}
```

- [ ] **Step 1: Failing API test**

Append to `tests/test_agent_api.py` (reuse monkeypatch patterns from `test_keyless_custom_chat_...`):

```python
def test_agent_chat_stream_sse(client, monkeypatch):
    # Ensure project "noor" exists via existing client fixture setup
    chunks = [
        b'data: {"choices":[{"delta":{"content":"ab"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    class _StreamResp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def __iter__(self):
            return iter(chunks)

    monkeypatch.setattr("daemon.llm_client._open_http", lambda req, timeout=120.0: _StreamResp())
    # Configure a key / provider the same way other chat tests do in this file
    # (put settings with a provider + api key, or rely on env key used by suite)

    with client.stream("POST", "/api/projects/noor/agent/chat/stream", json={"message": "hi"}) as res:
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")
        body = "".join(res.iter_text())
    assert "event: meta" in body
    assert "event: content_delta" in body
    assert "event: done" in body
```

Adapt fixture/settings setup to match whatever `test_keyless_custom_chat_does_not_send_loom_env_key` uses so the runtime resolves an LLM.

Also add:

```python
def test_agent_chat_stream_missing_project_404(client):
    res = client.post("/api/projects/missing/agent/chat/stream", json={"message": "hi"})
    assert res.status_code == 404
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTHONPATH=. python -m pytest tests/test_agent_api.py::test_agent_chat_stream_sse tests/test_agent_api.py::test_agent_chat_stream_missing_project_404 -v
```

- [ ] **Step 3: Implement runtime `chat_stream`**

Mirror `chat()` setup through history build. Then:

```python
async def chat_stream(self, project_id, project_path, payload):
    # validate llm.available → raise LlmError
    # create/load chat, add user message, build chat_msgs (same as chat)
    yield {"event": "meta", "chat_id": chat.id}
    reply = ""
    reasoning = None
    suggestion_id = None
    try:
        if payload.task_id:
            # one-shot: reuse existing chat() body path OR inline orch.run_suggest_cycle
            result = await self.chat(project_id, project_path, payload)
            # NOTE: chat() would double-insert user message — DO NOT call chat() blindly.
            # Instead duplicate the task_id branch from chat() without re-adding the user message.
            ...
            if reply:
                yield {"event": "content_delta", "text": reply}
            if reasoning:
                yield {"event": "reasoning_delta", "text": reasoning}
        else:
            # Refactor _project_chat_reply to accept a stream flag OR add
            # _project_chat_reply_stream that calls llm.chat_stream in to_thread
            # and yields deltas; accumulate reply/reasoning.
            ...
        await self.registry.add_agent_message(chat.id, "assistant", reply, reasoning_content=reasoning)
        if self.emit_event:
            await self.emit_event("agent:message", project_id, {...})
        yield {"event": "done", "chat_id": chat.id, "reply": reply, "reasoning": reasoning, "suggestion_id": suggestion_id}
    except Exception as e:
        if reply or reasoning:
            await self.registry.add_agent_message(chat.id, "assistant", reply or "", reasoning_content=reasoning)
        yield {"event": "error", "message": str(e)}
```

**Critical:** Extract shared “prepare chat + user message + history” helper used by both `chat` and `chat_stream` so the user message is only inserted once. For the task_id branch inside `chat_stream`, copy the orchestrator block from `chat` (do not re-enter `chat()`).

For project streaming, run the sync generator safely:

```python
def _pump():
    return list(llm.chat_stream(messages, model))

deltas = await asyncio.to_thread(_pump)
for d in deltas:
    if d.kind == "reasoning":
        reasoning = (reasoning or "") + d.text
        yield {"event": "reasoning_delta", "text": d.text}
    else:
        reply += d.text
        yield {"event": "content_delta", "text": d.text}
```

True mid-flight async yielding (token-by-token without buffering the whole stream) is better UX — prefer a thread + `asyncio.Queue` pump if straightforward; buffering the full stream in a thread is acceptable for v1 **only if** documented. Prefer queue pump:

```python
loop = asyncio.get_running_loop()
queue: asyncio.Queue = asyncio.Queue()

def worker():
    try:
        for d in llm.chat_stream(messages, model):
            loop.call_soon_threadsafe(queue.put_nowait, d)
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, None)

threading.Thread(target=worker, daemon=True).start()
while True:
    item = await queue.get()
    if item is None:
        break
    ...
```

- [ ] **Step 4: Implement API route**

```python
from fastapi.responses import StreamingResponse
import json

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.post("/api/projects/{project_id}/agent/chat/stream")
async def agent_chat_stream(project_id: str, payload: AgentChatRequest):
    project = await registry.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    async def gen():
        try:
            async for item in _get_agent_runtime().chat_stream(project_id, project.project_path, payload):
                ev = item.pop("event")
                yield _sse(ev, item if ev != "error" else item)
        except LlmError as e:
            yield _sse("error", {"message": str(e)})
        except ValueError as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
```

Pre-stream 404 for missing project stays as HTTPException (test above). LlmError before first yield can be HTTP 400 **or** SSE `error` — match the test; prefer raising HTTP 400 if key missing before `StreamingResponse` starts (check `llm.available` in the route or runtime before returning the response). Simplest: let runtime yield `error` only after `meta`; for missing key, raise `LlmError` in route setup by peeking settings like `chat` does — duplicate the availability check before creating `StreamingResponse` and `raise HTTPException(400)`.

- [ ] **Step 5: Tests PASS + non-stream regression**

```bash
PYTHONPATH=. python -m pytest tests/test_agent_api.py::test_agent_chat_stream_sse tests/test_agent_api.py::test_agent_chat_stream_missing_project_404 tests/test_agent_api.py::test_chat_without_key_returns_400 -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add daemon/agent_runtime.py daemon/api.py tests/test_agent_api.py
git commit -m "$(cat <<'EOF'
feat(daemon): SSE endpoint for streaming agent chat

EOF
)"
```

---

### Task 9: Dashboard `agentChatStream` + live bubble updates

**Files:**
- Modify: `dashboard/lib/api.ts`
- Modify: `dashboard/components/loom-agent-chat.tsx`
- Test: manual streaming; abort on unmount optional

**Interfaces:**
- Consumes: SSE endpoint from Task 8; `ChatMarkdown` from Task 1
- Produces:
  - `export type AgentChatStreamHandlers = { onMeta?: (chatId: string) => void; onReasoningDelta?: (text: string) => void; onContentDelta?: (text: string) => void; onDone?: (result: { chat_id: string; reply: string; reasoning: string | null; suggestion_id: string | null }) => void; onError?: (message: string) => void }`
  - `export async function agentChatStream(projectId: string, payload: { message: string; task_id?: string; chat_id?: string }, handlers: AgentChatStreamHandlers, signal?: AbortSignal): Promise<void>`

- [ ] **Step 1: Implement `agentChatStream` in `api.ts`**

```ts
export async function agentChatStream(
  projectId: string,
  payload: { message: string; task_id?: string; chat_id?: string },
  handlers: AgentChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/agent/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `chat stream failed (${res.status})`);
  }
  if (!res.body) throw new Error("chat stream returned empty body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const lines = part.split("\n");
      let event = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const json = JSON.parse(data) as Record<string, unknown>;
      if (event === "meta" && typeof json.chat_id === "string") handlers.onMeta?.(json.chat_id);
      else if (event === "reasoning_delta" && typeof json.text === "string") handlers.onReasoningDelta?.(json.text);
      else if (event === "content_delta" && typeof json.text === "string") handlers.onContentDelta?.(json.text);
      else if (event === "done") {
        handlers.onDone?.({
          chat_id: String(json.chat_id ?? ""),
          reply: String(json.reply ?? ""),
          reasoning: (json.reasoning as string | null) ?? null,
          suggestion_id: (json.suggestion_id as string | null) ?? null,
        });
      } else if (event === "error") {
        handlers.onError?.(String(json.message ?? "chat stream error"));
      }
    }
  }
}
```

- [ ] **Step 2: Wire `send()` in `loom-agent-chat.tsx`**

Replace the `agentChat(...)` call with streaming:

```tsx
setMessages((m) => [...m, { role: "user", content: text }, { role: "assistant", content: "", reasoning: null }]);
const assistantIndex = /* messages.length + 1 after user push — compute carefully */;

await agentChatStream(
  projectId,
  { message: text, task_id: taskId || undefined, chat_id: chatId },
  {
    onMeta: (id) => setChatId(id),
    onReasoningDelta: (chunk) => {
      setMessages((rows) => {
        const next = [...rows];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, reasoning: (last.reasoning || "") + chunk };
        }
        return next;
      });
    },
    onContentDelta: (chunk) => {
      setMessages((rows) => {
        const next = [...rows];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, content: last.content + chunk };
        }
        return next;
      });
    },
    onDone: async (result) => {
      setChatId(result.chat_id);
      setMessages((rows) => {
        const next = [...rows];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = {
            role: "assistant",
            content: result.reply || last.content,
            reasoning: result.reasoning ?? last.reasoning,
          };
        }
        return next;
      });
      if (!result.reply && !result.reasoning) setError(t("emptyReply"));
      if (result.suggestion_id && onSuggestion) onSuggestion(result.suggestion_id);
      await refreshSessions();
    },
    onError: (message) => setError(message),
  },
);
```

Keep the busy spinner until the first delta arrives (optional: hide spinner once content or reasoning non-empty).

On soft failure to start stream (network), show `chatError`; do **not** auto-fall back unless easily added — YAGNI per spec optional fallback.

- [ ] **Step 3: Manual E2E**

Start daemon + dashboard, send a project chat message, confirm tokens appear live and final Markdown formats. Task-scoped chat still returns a full reply (one-shot stream).

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/api.ts dashboard/components/loom-agent-chat.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): consume agent chat SSE into live bubbles

EOF
)"
```

---

### Task 10: Full regression sweep

**Files:** none new

- [ ] **Step 1: Pytest**

```bash
cd /Volumes/MO01/Offload/my-projects/agentic-os
PYTHONPATH=. python -m pytest tests/test_llm_clients_providers.py tests/test_agent_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Dashboard lint**

```bash
cd dashboard && npm run lint
```

Expected: PASS.

- [ ] **Step 3: Manual checklist**

- [ ] Markdown headings/lists/code in assistant + user + thinking
- [ ] Zoom buttons + shortcuts + persistence
- [ ] Copy message / thinking / code
- [ ] Sidebar preview not raw MD markers
- [ ] Suggestion prose Markdown
- [ ] Project chat streams; task chat still works
- [ ] Archive/delete sessions still work
- [ ] Non-stream `POST .../agent/chat` still works (curl or existing test)

- [ ] **Step 4: Final commit only if sweep fixed anything**; otherwise stop.

---

## Spec coverage self-review

| Spec requirement | Task(s) |
|------------------|---------|
| GFM + highlighted code component | 1 |
| User / assistant / thinking Markdown | 2 |
| Font zoom header + shortcuts + localStorage | 3 |
| Copy message / thinking / code | 4 |
| Sidebar preview Markdown | 5 |
| Suggestion prose Markdown | 5 |
| OpenAI + Anthropic `chat_stream` | 6, 7 |
| Runtime + SSE endpoint; keep non-stream | 8 |
| Dashboard live stream UI | 9 |
| i18n en/ar | 3, 4 |
| Partial persist on stream error | 8 |
| Task chat one-shot via stream path | 8, 9 |
| Tests + lint | 6–10 |

## Placeholder / consistency scan

- No TBD/TODO left in steps.
- Event names consistent: `meta` / `reasoning_delta` / `content_delta` / `done` / `error`.
- `StreamDelta.kind` is `"reasoning" | "content"`; API maps to `*_delta` events.
- localStorage key matches spec: `loom-agent-chat-font-scale`.
- Soft non-stream fallback intentionally omitted (optional in spec).
