# Agent Chat Markdown, Zoom & Streaming — Design

**Date:** 2026-11-24  
**Status:** Approved (written-spec review 2026-11-24)  
**Related:**
- `dashboard/components/loom-agent-chat.tsx` — Agent session sidebar + transcript bubbles
- `dashboard/components/suggestion-chip.tsx` — Suggestion prose currently plain text
- `dashboard/lib/api.ts` — `agentChat`, chat list/messages helpers
- `daemon/api.py` — `POST /api/projects/{id}/agent/chat`
- `daemon/agent_runtime.py` — `AgentRuntime.chat`
- `daemon/llm_client.py` — non-streaming `LlmClient.chat` / `AnthropicLlmClient.chat`
- `docs/superpowers/specs/2026-11-24-agent-chat-session-archive-delete-design.md` — session sidebar UX

---

## 1. Summary

Improve Loom Agent chat readability and interactivity:

1. **Markdown rendering** (GFM + syntax-highlighted fenced code) for user bubbles, assistant bubbles, thinking content, session sidebar previews, and suggestion chip prose.
2. **Chat-local font zoom** via header controls and keyboard/scroll shortcuts, persisted in `localStorage`.
3. **True token streaming** from the daemon (SSE/NDJSON) so replies and reasoning update live while Markdown reflows.
4. **Copy affordances** on assistant messages (and thinking / code blocks).

### Non-negotiable constraints

- Filesystem inbox protocol and single-process daemon model unchanged.
- Existing non-streaming `POST .../agent/chat` remains for tests, scripts, and fallback.
- No `rehype-raw` / raw HTML from model text (XSS-safe Markdown only).
- Zoom scales the chat panel only — not the whole dashboard.
- Streaming must work for OpenAI-compatible chat providers and Anthropic; failures surface as structured stream errors, not hung UIs.
- Existing dashboard dark zinc styling preserved; no new purple/glow aesthetic.
- Do not push or merge unless explicitly asked.

---

## 2. Decisions (from brainstorming)

| Fork | Decision |
|------|----------|
| Markdown scope | All bubbles: user, assistant, thinking (option C) |
| Markdown richness | GFM + highlighted code (option B) |
| Parser stack | `react-markdown` + `remark-gfm` + Shiki via `rehype-pretty-code` (approach 1) |
| Font zoom controls | Header `A−`/`A+` **and** Ctrl/Cmd ±/0 + Ctrl/Cmd+scroll (option C) |
| Streaming | Full daemon token stream + live UI (option A) |
| Formerly out of scope | Copy buttons, sidebar preview MD, suggestion prose MD — **in scope** |

---

## 3. Dashboard — Markdown

### 3.1 Component

Add `dashboard/components/chat-markdown.tsx` (`"use client"`):

| Prop | Type | Notes |
|------|------|--------|
| `content` | `string` | Source Markdown |
| `className` | `string?` | Wrapper classes |
| `variant` | `"default" \| "muted" \| "compact"` | `muted` for thinking; `compact` for sidebar preview / suggestion prose |

Behavior:

- Parse with `react-markdown` + `remark-gfm`.
- Highlight fenced code with `rehype-pretty-code` + `shiki` (dark theme aligned with zinc UI).
- Do **not** enable `rehype-raw`.
- Style headings, lists, links, tables, inline code, and code blocks for dense chat bubbles (tighter than default Tailwind `prose`).
- Empty `content` → render nothing.

### 3.2 Call sites

| Location | Variant |
|----------|---------|
| `loom-agent-chat.tsx` user / assistant message body | `default` |
| Thinking `<details>` body | `muted` |
| Session sidebar `previewLabel` text | `compact` + line-clamp (still truncate long previews) |
| `suggestion-chip.tsx` `suggestion.prose` | `compact` or `muted` |

Replace `whitespace-pre-wrap` plain text at those call sites. Keep bubble chrome (bg, padding, alignment) unchanged.

### 3.3 Dependencies (`dashboard/package.json`)

- `react-markdown`
- `remark-gfm`
- `rehype-pretty-code`
- `shiki`

(Exact versions pinned at install time; drop or swap highlighter only if Next 16 client bundling forces a simpler `rehype-highlight` fallback — document in the plan if needed.)

---

## 4. Dashboard — Font zoom

### 4.1 Mechanism

- Apply CSS variable `--chat-font-scale` on the root of the Loom Agent chat panel.
- Message area / Markdown / thinking inherit via `font-size: calc(… * var(--chat-font-scale))` (or equivalent rem scaling on the panel).
- Discrete steps, e.g. `0.875`, `1`, `1.125`, `1.25`, `1.5` (clamp at ends).
- Persist key: `loom-agent-chat-font-scale` in `localStorage`.
- Default: `1`.

### 4.2 Controls

- Header buttons: decrease / increase (optional % label), next to Settings.
- When the chat panel is focused or pointer-hovered:
  - `Ctrl/Cmd +` / `=` → increase
  - `Ctrl/Cmd -` → decrease
  - `Ctrl/Cmd 0` → reset to `1`
  - `Ctrl/Cmd + wheel` over the transcript → step zoom
- Buttons need accessible labels (i18n in `messages/en.json` + `messages/ar.json`).
- Do not prevent normal browser page zoom outside this panel’s shortcut handlers.

---

## 5. Daemon — Streaming chat

### 5.1 Problem

`AgentRuntime.chat` awaits a full `llm.chat(...)` string. Providers already support streams, but Loom does not expose them.

### 5.2 LLM client

Extend `daemon/llm_client.py`:

- Add a streaming API on the protocol / clients, e.g. `chat_stream(messages, model) -> Iterator[StreamEvent]` (sync generator run via `asyncio.to_thread` / async generator — pick one pattern and stick to it in the plan).
- `StreamEvent` kinds:
  - `reasoning_delta` — incremental reasoning / thinking text (when the provider supplies it)
  - `content_delta` — incremental assistant reply text
  - `usage` (optional) — token counts if available mid/end stream
- Keep existing `chat()` for non-stream callers; implement `chat()` via consuming the stream or keep the current non-stream HTTP path (prefer least churn that stays correct for reasoning capture).
- Cover OpenAI-compatible (`LlmClient`) and `AnthropicLlmClient`. Custom providers using OpenAI-compatible base URLs inherit stream support.

### 5.3 Runtime

Extend `AgentRuntime` with `chat_stream(...)` that:

1. Performs the same setup as `chat` (resolve project/settings/history, create/reuse chat row, persist user message).
2. Yields stream events to the API layer.
3. On completion: persist assistant message (+ `reasoning_content`), run suggestion side-effects as today, yield a final `done` payload (`chat_id`, full `reply`, `reasoning`, `suggestion_id`).
4. On failure after partial output: yield `error`; persist policy — prefer persisting the partial assistant text if any was received, documented in implementation plan tests.

### 5.4 API

| Method | Path | Behavior |
|--------|------|----------|
| `POST` | `/api/projects/{project_id}/agent/chat` | **Unchanged** non-stream JSON response |
| `POST` | `/api/projects/{project_id}/agent/chat/stream` | Same request body as `AgentChatRequest`; response is **SSE** (`text/event-stream`) or **NDJSON** (`application/x-ndjson`) |

**Event payload (logical):**

| Event | Fields |
|-------|--------|
| `meta` | `chat_id` (emitted once early) |
| `reasoning_delta` | `text` |
| `content_delta` | `text` |
| `done` | `chat_id`, `reply`, `reasoning`, `suggestion_id` |
| `error` | `message` (HTTP may still be 200 with terminal error event for mid-stream failures; pre-stream validation errors remain normal HTTP 4xx) |

**Transport choice:** prefer SSE with `data: {json}\n\n` and `event:` names matching the table above. If CORS/proxy friction appears with SSE POST, NDJSON over the same path is an acceptable equivalent — pick one in the implementation plan and test it.

Auth / CORS: same as existing agent chat (localhost dashboard origin).

### 5.5 Tests

- Unit: LLM stream parsing (mocked HTTP chunks → deltas).
- API: stream endpoint emits `meta` → deltas → `done`; error path; project 404.
- Regression: non-stream `POST .../agent/chat` still green.

---

## 6. Dashboard — Streaming client

### 6.1 API helper

Add `agentChatStream(...)` in `lib/api.ts` that:

- `fetch`es the stream endpoint with the same body as `agentChat`.
- Parses SSE/NDJSON events and invokes callbacks / async iterator for `meta`, `reasoning_delta`, `content_delta`, `done`, `error`.
- Supports `AbortController` so navigating away or “stop” (if added later) cancels the request.

### 6.2 UI behavior in `loom-agent-chat.tsx`

1. On send: append user message; append empty assistant bubble (and empty reasoning details when first reasoning delta arrives).
2. Apply deltas to that bubble’s state; re-render `ChatMarkdown` from the accumulating string.
3. Optional light debounce (e.g. rAF / 50–100ms) if re-parse jank appears; not required for v1 if performance is fine.
4. On `done`: finalize content, refresh sessions list, fire `onSuggestion` if `suggestion_id` present.
5. On `error`: show error line; keep any partial content already shown.
6. Mid-stream incomplete Markdown (unclosed fences, etc.) is acceptable visual noise until the next chunks arrive.
7. Loading indicator: replace or supplement the current “thinking…” spinner with the live growing bubble once the first delta arrives.

Wire `send()` to the stream helper by default; keep non-stream helper available for fallback if stream endpoint fails to start (optional soft fallback — document in plan).

---

## 7. Copy controls

On each **assistant** bubble:

- Icon button: **Copy message** (clipboard of final/current `content`).
- If reasoning exists: **Copy thinking** (or a single menu with both actions).
- Fenced code blocks rendered by `ChatMarkdown`: hover **Copy** on the code block.

Feedback: brief checkmark / toast-free label swap (“Copied”) for ~1.5s. i18n strings in en/ar.

User bubbles: no copy required (out of minimal chrome), but not forbidden if trivial.

---

## 8. Sidebar preview & suggestions

- **Sidebar:** strip or render Markdown compactly; keep ~48-char / 2-line clamp so the list stays dense. Prefer rendering compact Markdown over showing raw `##` / `**`.
- **Suggestions:** `suggestion.prose` uses `ChatMarkdown` with compact/muted styling inside the existing chip layout.

---

## 9. i18n

Add strings (en + ar) for:

- Zoom in / out / reset labels and `%` if shown
- Copy message / copy thinking / copy code / copied
- Any stream-specific errors if distinct from existing `chatError`

---

## 10. Out of scope (remaining)

- Stop-generation button (AbortController may exist internally; UI stop is optional follow-up)
- Per-message regenerate / edit
- Message search
- Changing agent system prompts or provider protocols beyond stream deltas
- Desktop Tauri-specific font zoom (inherits webview behavior unless a separate issue)

---

## 11. Success criteria

- Agent replies with headings, lists, bold, tables, and fenced code read as formatted UI — not raw markers.
- User, thinking, sidebar preview, and suggestion prose also format correctly.
- Font zoom changes chat text size via header and shortcuts; survives reload via `localStorage`.
- Streaming shows incremental assistant (and reasoning when provided) without waiting for the full reply.
- Copy actions put the expected text on the clipboard.
- Non-stream chat endpoint and existing archive/delete session UX remain intact.
- Pytest + dashboard lint stay green for touched areas.
