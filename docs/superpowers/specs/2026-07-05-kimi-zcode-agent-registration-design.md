# Design: Register Kimi Code and ZCode as Built-in Agents

## Goal

Add **Kimi Code** and **ZCode** to the Loom OS built-in agent catalog so users can register them through the existing `loom register` CLI, `loom detect-agents`, the dashboard "Register Agent" modal, and the `/api/agents/known` endpoint.

Both agents participate through the same filesystem inbox protocol as Claude Code and Codex; this change only adds recognition, auto-detection, and dashboard UI polish.

## Context

Loom OS already maintains a canonical agent catalog in `daemon/known_agents.py` (`KNOWN_AGENTS`) and a runtime detection function `detect_installed()`. The dashboard consumes this catalog via `GET /api/agents/known` and renders:

- Installed agents as quick-fill chips in `RegisterAgentModal`.
- Non-installed agents as a secondary "Other known agents" list.
- Registered agents as `AgentCard` components, which derive generic initials and status colors from the agent name.

Current supported agents include Claude Code, Codex, Hermes, Gemini CLI, Copilot CLI, Aider, OpenCode, and Cursor. Cursor is detected by its macOS app bundle rather than a CLI binary.

## Design

### 1. Backend: agent catalog

Add two entries to `KNOWN_AGENTS` in `daemon/known_agents.py`:

| canonical name | display name | detection | default version | default capabilities |
|---|---|---|---|---|
| `kimi-code` | Kimi Code | CLI binary `kimi` on PATH | `1.0` | `code-analysis`, `generation`, `refactoring` |
| `zcode` | ZCode | macOS app bundle `ZCode.app` | `1.0` | `code-analysis`, `generation`, `long-context`, `review` |

**Kimi Code detection.** `shutil.which("kimi")` returns the path when the [Kimi Code CLI](https://www.moonshot.cn/kimi/code) is installed.

**ZCode detection.** ZCode is a desktop application; public documentation describes it as a visual harness for GLM-5.2 rather than a public CLI ([ZCode docs](https://zcode.z.ai/en/docs/welcome), [feature request noting Zhipu AI CLI](https://github.com/nexu-io/open-design/issues/4692)). Detection mirrors Cursor: look for `/Applications/ZCode.app`, then `~/Applications/ZCode.app`. The `detect_cmd` field is `None` and a dedicated `_detect_zcode()` helper is added.

`detect_installed()` is updated to call `_detect_zcode()` for the `zcode` entry. No database schema changes are required.

### 2. Frontend: avatar and quick-pick polish

`AgentCard` currently builds initials from `agent_name` (e.g. "Claude Code" → "CC"). To make Kimi Code and ZCode recognizable at a glance, add a small `AGENT_AVATAR` map keyed by canonical agent name:

| agent | initials | default avatar background |
|---|---|---|
| `claude-code` | CC | emerald |
| `codex` | CX | blue |
| `kimi-code` | KM | indigo |
| `zcode` | ZC | violet |
| fallback | first two letters | zinc |

`AgentCard` uses the map when the registered `agent_name` matches a known canonical name; otherwise it keeps the existing fallback.

`RegisterAgentModal` already renders quick-pick chips from `/api/agents/known`. Each chip is updated to show the agent `description` as a native `title` tooltip on hover, so users know what Kimi Code and ZCode are before selecting them.

### 3. Internationalization and docs

- `dashboard/messages/en.json`: update `RegisterAgentModal.agentNamePlaceholder` from `"e.g. claude-code, codex"` to `"e.g. claude-code, codex, kimi-code, zcode"`.
- `dashboard/messages/ar.json`: update the Arabic placeholder to include the new canonical names.
- `docs/AGENT-LIFECYCLE.md`: add Kimi Code and ZCode to the **Supported Agents** list.

### 4. Testing

Add tests in `tests/test_known_agents.py` (or extend the existing known-agents test file):

- `test_kimi_code_detected_when_kimi_on_path`: mock `shutil.which("kimi")` returning a path and assert `kimi-code` is in `detect_installed()`.
- `test_zcode_detected_when_app_bundle_present`: mock `Path.exists()` for `/Applications/ZCode.app` and assert `zcode` is in `detect_installed()`.
- `test_get_known_agents_includes_new_agents`: assert `KNOWN_AGENTS` contains entries with names `kimi-code` and `zcode`.

Dashboard changes are verified by the existing TypeScript build (`npm run build` in `dashboard/`) and a quick visual check of the Register Agent modal.

### 5. Files to modify

- `daemon/known_agents.py`
- `dashboard/components/agent-card.tsx`
- `dashboard/components/register-agent-modal.tsx`
- `dashboard/messages/en.json`
- `dashboard/messages/ar.json`
- `docs/AGENT-LIFECYCLE.md`
- `tests/test_known_agents.py` (new or updated)

## Error handling

- If the `kimi` binary or the `ZCode.app` bundle is absent, the agents simply appear in the "Other known agents" list (not installed). This matches current behavior for non-installed agents.
- The dashboard quick-pick falls back to the server-provided `display` name and description; missing avatar entries use the existing generic initials.
- No new API endpoints or auth flows are introduced, so existing error paths remain unchanged.

## Data flow

1. Daemon startup / dashboard load calls `GET /api/agents/known`, which merges `KNOWN_AGENTS` with `detect_installed()`.
2. `kimi-code` is marked installed when `kimi` is on PATH; `zcode` is marked installed when the macOS app bundle exists.
3. User opens "Register Agent" in the dashboard and sees installed agents as clickable chips, including Kimi Code / ZCode when detected.
4. Clicking a chip auto-fills `agent`, `version`, and `capabilities` from the catalog defaults.
5. On submit, the existing `/api/projects/{id}/register-agent` writes `register.json` to the inbox; the daemon processes it the same way as any agent.
6. Once registered, `AgentCard` renders the agent with its mapped avatar initials and status styling.

## Out of scope

- Bundling or installing the Kimi Code / ZCode binaries.
- Changing the filesystem inbox protocol.
- Adding custom per-agent task runners (they still use the generic worker/dispatch flow).
- Windows or Linux app-bundle detection for ZCode (macOS only, matching Cursor).

## Open questions

None remaining for this scope.
