# Loom Coding Agent Desktop (Tauri) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Tauri 2 desktop shell that boots the local Loom stack, opens on an Agent-focused Next route (no system browser), and embeds the full Dashboard in-app via a single webview + tab chrome.

**Architecture:** Rust owns PATH bootstrap, support-dir install, process lifecycle (daemon `:8472` + Next `:3000`), health wait, and graceful shutdown. A minimal TS chrome switches Agent ↔ Dashboard by navigating one webview. Next gains `/{locale}/agent-app` that reuses existing Loom Agent components. Packaged builds run `next start` after build; `tauri dev` prefers an already-running stack.

**Tech Stack:** Tauri 2 (Rust + TS), Next.js 16 dashboard (`en`/`ar`), existing `loom` CLI / venv / `npm`, Warp branding SVG→icons.

**Spec:** `docs/superpowers/specs/2026-11-22-loom-coding-agent-desktop-tauri-design.md`

## Global Constraints

- Shell is **Tauri 2**; do not introduce Electron / Flutter / Swift-only UI
- **Never** auto-open the system browser on launch; optional menu item only (`open_external_dashboard`)
- Single webview + tab chrome (Agent → `/{locale}/agent-app`, Dashboard → `/{locale}/` or last Dashboard path)
- Default locale for shell URLs: `en` (`routing.defaultLocale`)
- Health: daemon `GET http://127.0.0.1:8472/api/health`; dashboard `GET http://127.0.0.1:3000/` (any 2xx)
- Support root: mac `~/Library/Application Support/LoomCodingAgent/`, win `%APPDATA%\LoomCodingAgent\`, linux `~/.local/share/LoomCodingAgent/`
- Packaged stack: `pip install -e ".[llm]"` into support-dir venv; `next build` then `next start` on `:3000`
- `tauri dev`: if both ports already healthy, attach (do not spawn); else spawn with `next dev` when shell starts Next
- Quit app → stop only child processes **this shell started** (do not kill pre-attached external stack)
- i18n: every new dashboard UI string in both `messages/en.json` and `messages/ar.json`
- Bundle id / product name align with interim app: `os.loom.coding-agent`, display name `Loom Coding Agent`
- Icon source: `docs/branding/loom-icon-warp.svg` (generate raster/icons in packaging; do not invent a second brand)
- Do not push / open / merge without explicit user approval
- Interim `scripts/packaging/macos/build-dmg.sh` may remain but docs must point primary ship path at `tauri build`

## Review Focus

- GUI launch with empty PATH still finds Homebrew/nvm/Hermes/login-shell node+python → Task 2
- Ports already occupied by a healthy stack → shell attaches, does not double-spawn, quit leaves them running → Task 3
- Launch never opens Safari/Chrome; only `open_external_dashboard` does → Task 4
- Missing `project` query → Agent page shows picker; with `?project=&task=` chat binds correctly → Task 5
- App quit kills daemon+Next children started by the shell (process tree, not orphaned Next) → Task 3

## File map

| Path | Responsibility |
|------|----------------|
| `desktop/` | Tauri 2 project root (package.json, Vite/TS shell) |
| `desktop/src/main.ts` (+ HTML/CSS) | Tab chrome: Agent \| Dashboard; invoke IPC; navigate webview |
| `desktop/src-tauri/src/main.rs` | Tauri setup, window show after stack ready |
| `desktop/src-tauri/src/path_bootstrap.rs` | PATH prepend + login-shell merge (port of interim launcher) |
| `desktop/src-tauri/src/support.rs` | OS support-root paths, logs dir, payload/install layout |
| `desktop/src-tauri/src/stack.rs` | Ensure venv/deps, spawn/attach, health poll, shutdown tree |
| `desktop/src-tauri/src/commands.rs` | `stack_status`, `restart_stack`, `open_external_dashboard`, `get_paths` |
| `desktop/src-tauri/tauri.conf.json` | Bundle id, windows, icons, CSP allowing `127.0.0.1` |
| `desktop/src-tauri/icons/` | Generated Warp app icons |
| `dashboard/app/[locale]/agent-app/page.tsx` | Agent-focused page (searchParams) |
| `dashboard/components/agent-app-shell.tsx` | Project picker + chat + implement/progress wiring |
| `dashboard/messages/{en,ar}.json` | `AgentApp` strings |
| `coding_agent/README.md`, root `README.md` | Document Tauri as primary desktop ship path |
| `tests/test_desktop_path_bootstrap.py` | Optional thin checks **or** prefer Rust unit tests in `path_bootstrap.rs` — use Rust `#[cfg(test)]` as primary |
| `scripts/packaging/macos/README.md` (or section in coding_agent README) | Note interim DMG superseded; `cd desktop && npm run tauri build` |

---

### Task 1: Scaffold `desktop/` Tauri 2 + Warp icons + tab chrome

**Files:**
- Create: `desktop/` Tauri 2 app (official create-tauri-app defaults OK if product name / identifier match Global Constraints)
- Create: `desktop/src/` tab UI (Agent \| Dashboard buttons; title `Loom Coding Agent`)
- Create: `desktop/src-tauri/icons/` from Warp SVG (export 512 PNG then `tauri icon` or equivalent)
- Modify: `desktop/src-tauri/tauri.conf.json` — identifier `os.loom.coding-agent`, productName `Loom Coding Agent`

**Interfaces:**
- Produces: runnable `cd desktop && npm run tauri dev` window with two tabs that change a **placeholder** URL string in the chrome (real navigation wired in Task 4)
- Tab ids: `"agent" | "dashboard"`; default selected `"agent"`

- [ ] **Step 1: Scaffold** Tauri 2 project under `desktop/` with TS + Vite frontend

- [ ] **Step 2: Generate icons** from `docs/branding/loom-icon-warp.svg` into `desktop/src-tauri/icons/`

- [ ] **Step 3: Implement tab chrome** with Agent (default) and Dashboard tabs; no system browser open

- [ ] **Step 4: Verify** `cd desktop && npm run tauri dev` opens a titled window with both tabs selectable

- [ ] **Step 5: Commit** `feat(desktop): scaffold Tauri 2 shell with Warp icons and tabs`

---

### Task 2: PATH bootstrap + support directories (pure Rust, unit-tested)

**Files:**
- Create: `desktop/src-tauri/src/path_bootstrap.rs`
- Create: `desktop/src-tauri/src/support.rs`
- Modify: `desktop/src-tauri/src/main.rs` (mod + call bootstrap early in setup)
- Test: `#[cfg(test)]` inside those modules

**Interfaces:**
- Produces:
  - `pub fn bootstrap_path(env_path: &str, home: &Path) -> String` — prepends, in order if present: `/opt/homebrew/bin`, `/opt/homebrew/sbin`, `/usr/local/bin`, Homebrew `node@24|22|20` bins, `~/.hermes/node/bin`, `~/.local/bin`, `~/.bun/bin`, latest `~/.nvm/versions/node/*/bin`, latest `~/.fnm/node-versions/*/installation/bin`; then appends login-shell PATH from `/bin/zsh -lc` (or bash) without dropping earlier entries
  - `pub fn apply_path_to_process(path: &str)` — sets process `PATH`
  - `pub fn support_root(home: &Path, os: &str) -> PathBuf` — mac → `Library/Application Support/LoomCodingAgent`, linux → `.local/share/LoomCodingAgent`, windows → use `dirs`/`known_folders` equivalent under `%APPDATA%\LoomCodingAgent` (tests cover mac+linux path joins; win via `cfg`)
  - `pub fn logs_dir(root: &Path) -> PathBuf` → `root.join("logs")`
  - `pub fn install_dir(root: &Path) -> PathBuf` → `root.join("app")`

- [ ] **Step 1: Write failing unit tests** for `bootstrap_path` (empty PATH + fake home with homebrew+nvm stubs via temp dirs) and `support_root` mac/linux

- [ ] **Step 2: Run** `cd desktop/src-tauri && cargo test path_bootstrap support -- --nocapture` — expect FAIL (modules missing)

- [ ] **Step 3: Implement** `path_bootstrap.rs` and `support.rs`; call `bootstrap_path` + `apply_path_to_process` at start of Tauri setup

- [ ] **Step 4: Run tests** — PASS

- [ ] **Step 5: Commit** `feat(desktop): PATH bootstrap and LoomCodingAgent support dirs`

---

### Task 3: Stack lifecycle — ensure deps, spawn/attach, health, shutdown

**Files:**
- Create: `desktop/src-tauri/src/stack.rs`
- Modify: `desktop/src-tauri/src/main.rs` (run ensure+wait before showing window; register Exit cleanup)
- Test: `stack.rs` unit tests for pure helpers (`is_healthy` URL parse / status classification with a tiny local `HttpServer` or mocked transport)

**Interfaces:**
- Consumes: `support::install_dir`, bootstrapped `PATH`
- Produces:
  - `pub struct StackConfig { pub daemon_url: String /* http://127.0.0.1:8472 */, pub dashboard_url: String /* http://127.0.0.1:3000 */, pub install_root: PathBuf, pub packaged: bool }`
  - `pub struct StackManager` with fields tracking `owned: bool`, child PIDs/process groups
  - `pub async fn probe_healthy(daemon_url: &str, dashboard_url: &str) -> bool` — true iff daemon `/api/health` OK and dashboard `/` 2xx
  - `pub async fn StackManager::ensure_and_start(&mut self, cfg: &StackConfig) -> Result<()>` — if `probe_healthy`, set `owned=false` and return; else ensure venv + `pip install -e ".[llm]"`, ensure `dashboard/node_modules` (+ `next build` when `cfg.packaged`), spawn daemon (`loom start --host 127.0.0.1 --port 8472`) and Next (`npm run start` if packaged else `npm run dev`) with cwd `install_root` / `install_root/dashboard`, poll health up to ~40s, set `owned=true`
  - `pub fn StackManager::shutdown(&mut self)` — if `owned`, kill process trees for daemon and Next (same spirit as `run.sh` `kill_tree`); if not owned, no-op
  - Dev attach: when running under `tauri dev` and repo checkout is the install root, prefer repo root over copying payload (detect `LOOM_DESKTOP_REPO` env or `CARGO_MANIFEST_DIR`/`../../..`)

- [ ] **Step 1: Write failing tests** for `probe_healthy` true/false against a local test listener; shutdown no-op when `owned=false`

- [ ] **Step 2: Run** `cargo test stack::` — expect FAIL

- [ ] **Step 3: Implement** `stack.rs` and wire setup/exit in `main.rs` (show window only after healthy)

- [ ] **Step 4: Run tests** — PASS; manual: with stack already up via `./run.sh`, `tauri dev` attaches without second daemon

- [ ] **Step 5: Commit** `feat(desktop): local stack ensure, health wait, and owned shutdown`

---

### Task 4: IPC commands + single-webview navigation (no browser on launch)

**Files:**
- Create: `desktop/src-tauri/src/commands.rs`
- Modify: `desktop/src/main.ts` — on tab change, ask Rust to navigate the webview (or use Tauri webview API from frontend)
- Modify: `desktop/src-tauri/src/main.rs` — register commands; initial navigate to `http://127.0.0.1:3000/en/agent-app`
- Modify: `tauri.conf.json` — allow `http://127.0.0.1:3000` / `8472` in CSP / capabilities as required by Tauri 2

**Interfaces:**
- Produces Tauri commands:
  - `stack_status() -> StackStatus { daemon_ok: bool, dashboard_ok: bool, owned: bool, agent_url: String, dashboard_url: String }`
  - `restart_stack() -> Result<()>` — shutdown if owned, then `ensure_and_start`
  - `open_external_dashboard() -> Result<()>` — `opener`/`shell::open` on `http://127.0.0.1:3000/en` only when invoked
  - `get_paths() -> PathsDto { support_root: String, install_dir: String, logs_dir: String }`
- Shell: Agent tab → `http://127.0.0.1:3000/en/agent-app` (+ preserve `?project=&task=` if already on agent URL); Dashboard tab → `http://127.0.0.1:3000/en` or last non-agent path remembered in TS state
- Menu: “Open Dashboard in Browser” → `open_external_dashboard`

- [ ] **Step 1: Write failing Rust tests** for URL builders (agent vs dashboard base; query passthrough) if extracted as pure fns `agent_app_url(base, project, task) -> String`

- [ ] **Step 2: Implement commands + wire tabs to navigate single webview**; add menu item

- [ ] **Step 3: Verify** launch lands on Agent URL with **zero** system browser windows; menu opens browser once

- [ ] **Step 4: Commit** `feat(desktop): IPC stack commands and in-app Agent/Dashboard navigation`

---

### Task 5: Next.js `/agent-app` route (reuse Loom Agent components)

**Files:**
- Create: `dashboard/app/[locale]/agent-app/page.tsx`
- Create: `dashboard/components/agent-app-shell.tsx`
- Modify: `dashboard/messages/en.json`, `dashboard/messages/ar.json` — namespace `AgentApp`
- Read Next 16 docs under `dashboard/node_modules/next/dist/docs/` before coding the page (App Router / searchParams)

**Interfaces:**
- Consumes: `listProjects`, `LoomAgentChat`, `ImplementPickerModal`, `previewImplement` / `implementTask` (or existing helpers from `lib/api.ts`), task progress APIs / WS patterns from `task-detail-drawer.tsx` as needed — **reuse, do not fork** chat/picker
- Produces:
  - Page reads `searchParams`: `project?: string`, `task?: string`
  - If no `project`: show project picker (`listProjects`) then navigate/replace URL to `?project=<id>`
  - If `project` set: render `LoomAgentChat` with `projectId` + optional `taskId`; task select list (from `listAgentTasks`) updates `?task=`
  - Implement control for selected task opens same preview → `ImplementPickerModal` flow as drawer
  - Cancel run uses existing worker stop API when a run is active
- Layout: fit desktop shell (full viewport height, no marketing chrome); keep existing dark dashboard look

- [ ] **Step 1: Add i18n keys** `AgentApp` in en+ar (title, pickProject, noProjects, selectTask, implement, cancelRun, loading, stackHint)

- [ ] **Step 2: Implement** `agent-app/page.tsx` + `agent-app-shell.tsx`

- [ ] **Step 3: Verify** with dashboard running: `/en/agent-app` shows picker; `/en/agent-app?project=<id>` shows chat; with `&task=` scopes chat; `npm run lint` in `dashboard/`

- [ ] **Step 4: Commit** `feat(dashboard): agent-app desktop route reusing Loom Agent UI`

---

### Task 6: macOS `tauri build`, docs, interim DMG note

**Files:**
- Modify: `coding_agent/README.md` — primary desktop path = Tauri (`cd desktop && npm run tauri build`); interim `build-dmg.sh` marked secondary
- Modify: root `README.md` (desktop / coding agent mention if present) — same
- Optional: thin wrapper comment at top of `scripts/packaging/macos/build-dmg.sh` pointing to Tauri
- Ensure packaged config sets `StackConfig.packaged = true` (release profile) and bundles/copies payload into resources as needed for first-run install into support dir (mirror interim rsync set: `daemon/`, `coding_agent/`, `dashboard/`, `pyproject.toml`, `run.sh` — **without** opening browser)

**Interfaces:**
- Produces: macOS `.app` / `.dmg` via `tauri build` under `desktop/src-tauri/target/release/bundle/`
- Document win/linux: `npm run tauri build` produces NSIS/AppImage when run on those hosts (no requirement to produce them on mac CI in this task)

- [ ] **Step 1: Configure** release bundle resources + `packaged` flag

- [ ] **Step 2: Run** `cd desktop && npm run tauri build` on macOS — expect `.app` artifact

- [ ] **Step 3: Smoke** install/open `.app` → Agent tab, no Safari; Dashboard tab loads control plane; quit stops owned children

- [ ] **Step 4: Update READMEs** + interim script note

- [ ] **Step 5: Commit** `feat(desktop): macOS tauri build and document primary ship path`

---

## Spec coverage (self-review)

| Spec item | Task |
|-----------|------|
| Tauri 2 shell, Warp branding | 1 |
| PATH bootstrap (Homebrew/nvm/fnm/Hermes/login shell) | 2 |
| Support dir layout | 2 |
| Ensure venv/pip/npm, spawn daemon+Next, health wait | 3 |
| Quit → stop owned children; attach if healthy | 3 |
| IPC: stack_status, restart_stack, open_external, get_paths | 4 |
| Single webview tabs; no auto browser | 4 |
| `/agent-app` + reuse chat/implement; `?project=&task=` | 5 |
| Packaged `next start` vs dev attach/`next dev` | 3 + 6 |
| mac `tauri build`; win/linux documented; README | 6 |
| Interim DMG superseded as primary | 6 |
