# Loom Coding Agent Desktop (Tauri) — Design

**Date:** 2026-11-22  
**Status:** Draft — awaiting written-spec review  
**Related:**
- `coding_agent/README.md`
- `docs/superpowers/specs/2026-11-16-loom-coding-agent-pattern-routing-design.md`
- `scripts/packaging/macos/build-dmg.sh` (interim shell-script `.app`; superseded as primary ship path)

---

## 1. Summary

Ship a **cross-platform desktop app** (macOS, Windows, Linux) for the Loom **Coding Agent**:

- Default surface = **Agent** (focused coding-agent UX).
- Secondary surface = **Dashboard** (full Loom Next.js control plane), as an in-app section — **not** the system browser.
- Backend remains local: Python daemon (`:8472`) + Next dashboard (`:3000`) + extractable `coding_agent` package.

**Shell:** **Tauri 2** (Rust). UI stays web (Next.js). Rejected for v1: Electron (heavier), Flutter / pure Rust UI (would rewrite existing dashboard), Swift-only WKWebView (macOS-only).

---

## 2. Goals / non-goals

### Goals
- One installable app per OS that feels like an app window (Warp branding).
- On launch: start local stack → open Tauri window on **Agent** tab → never auto-open Chrome/Safari.
- **Dashboard** tab embeds `http://127.0.0.1:3000`.
- Agent tab uses a dedicated Next route that reuses existing chat / implement / progress components.
- PATH bootstrap for GUI launches (Homebrew, nvm/fnm, Hermes Node, login shell) — same class of fix as the interim `.app` launcher.

### Non-goals (v1)
- Cloud multi-tenant desktop.
- Rewriting Kanban/graph in a non-web UI.
- Running without the Next process (Dashboard section needs it).
- Mobile (iOS/Android).
- Replacing `loom` CLI / PyPI daemon packaging.

---

## 3. UX

```
┌──────────────────────────────────────────────────┐
│  [Warp] Loom Coding Agent     [ Agent | Dashboard ]│
├──────────────────────────────────────────────────┤
│  Agent (default)                                   │
│    · Project picker                                │
│    · Loom Agent chat + settings                    │
│    · Active task / live progress                   │
│    · Implement (preview → picker) + Cancel run     │
│  Dashboard                                         │
│    · WebView → http://127.0.0.1:3000/{locale}/…    │
└──────────────────────────────────────────────────┘
```

- Quit app → stop child processes (daemon + Next) started by the shell.
- Optional: “Open Dashboard in browser” as a menu item; default remains in-app.

---

## 4. Architecture

```
Tauri main (Rust)
  ├─ bootstrap PATH
  ├─ ensure install dir / venv / pip install loom-os[llm]
  ├─ ensure dashboard npm deps
  ├─ spawn daemon (loom start / uvicorn)
  ├─ spawn Next (dashboard npm run start|dev)
  ├─ wait until :8472 and :3000 healthy
  └─ show window
        ├─ Agent WebView  → http://127.0.0.1:3000/{locale}/agent-app
        └─ Dashboard WebView → http://127.0.0.1:3000/{locale}/…

Next.js (existing dashboard/)
  └─ new route: app/[locale]/agent-app/page.tsx
       reuses: loom-agent-chat, implement-picker-modal,
               task progress / settings panels
```

**IPC (Tauri commands):** `stack_status`, `restart_stack`, `open_external_dashboard` (optional), `get_paths` / logs dir.

**State location:** e.g. `~/Library/Application Support/LoomCodingAgent/` (mac), `%APPDATA%\LoomCodingAgent\` (win), `~/.local/share/LoomCodingAgent/` (linux) — payload, venv, logs.

---

## 5. Repo layout (proposed)

```
desktop/                          # Tauri 2 project
  src-tauri/                      # Rust: bootstrap, process mgmt, IPC
  src/                            # minimal TS shell: tab switcher (or pure Rust menu + dual webview)
  … packaging config …

dashboard/app/[locale]/agent-app/  # Agent-focused Next page

scripts/packaging/
  macos/build-dmg.sh              # keep or thin-wrap; primary builds via `tauri build`
  (later) documented win/linux via tauri-cli
```

Icon: `docs/branding/loom-icon-warp-512.png` → Tauri bundle icons.

---

## 6. Packaging

| OS | Artifact |
|----|----------|
| macOS | `.dmg` / `.app` via `tauri build` |
| Windows | NSIS / MSI |
| Linux | AppImage and/or deb |

Dev: `cargo tauri dev` with stack already running, or shell auto-start in debug too.

---

## 7. Decisions log

| Fork | Decision |
|------|----------|
| Shell | Tauri 2 (Rust), not Electron / Flutter / Swift-only |
| UI | Web (Next); Agent route + Dashboard embed |
| Browser | Do not auto-open system browser on launch |
| Stack | Local daemon + dashboard still required |
| Interim script DMG | Superseded as primary ship path once Tauri ships |

---

## 8. Implementation phases (outline)

1. Spec approved → implementation plan (`writing-plans`).
2. Scaffold `desktop/` Tauri 2 + Warp icon + tab shell.
3. Add `/agent-app` Next route (reuse components).
4. Rust bootstrap: PATH, venv, pip, npm, spawn/wait/health, graceful shutdown.
5. Wire Agent + Dashboard webviews; no system browser open.
6. `tauri build` for mac; document win/linux; update `coding_agent/README.md` + root README.

---

## 9. Open points (resolve in plan if needed)

- Dev vs prod Next: `next start` after `next build` in packaged app vs `next dev` in `tauri dev`.
- Single webview + client-side tab vs two webviews.
- Whether Agent tab is task-scoped (deep-link `?project=&task=`) in v1.
