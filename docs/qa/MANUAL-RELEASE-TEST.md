# Manual release test

Pre-release checklist for Loom OS. Target: **`v0.3.0-alpha.1`** (or the current RC on `main`). Budget: **~60–90 minutes**. Outcome: ship / no-ship with clear pass–fail.

Related: [CHANGELOG](../../CHANGELOG.md) · [User Guide](../USAGE.md) · [smoke-test.sh](../../scripts/smoke-test.sh) · [run.sh](../../run.sh)

---

## Pass / fail rules

| Severity | Meaning | Action |
|----------|---------|--------|
| **Blocker** | Daemon won’t start, dashboard disconnected, register/graph fails, Implement worker crash, corrupt `~/.loom/state.db` | **No-ship** |
| **Major** | Accept/Dismiss/Implement bugs, BYOK ignored, empty search/federation with graphs present, team auth write bypass | **Fix before announce** |
| **Minor** | Polish, i18n gaps, slow first graph build | Note in release notes |

**Ship** only with no Blockers and no open Majors.

---

## 0. Automated gate (~5 min)

```bash
git checkout v0.3.0-alpha.1   # or the RC commit
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q
bash scripts/smoke-test.sh
```

**Pass:** pytest green; smoke script prints `All smoke tests passed!`

---

## 1. Cold bring-up — `./run.sh` (~10 min)

1. From repo root: `./run.sh --open`
2. `curl -s http://127.0.0.1:8472/api/health` → body contains `"status":"ok"`
3. Open `http://localhost:3000` and `http://127.0.0.1:3000` — WebSocket shows **Connected**
4. Ctrl+C stops **both** daemon and dashboard (no orphan process still bound to `:3000`)

**Pass:** health OK, UI connected on both loopback hosts, clean shutdown.

---

## 2. Project + graph (~10 min)

1. In the dashboard, **Add Project** (this repo path is fine)
2. Graph explorer shows nodes/edges; click a node → detail panel opens
3. CLI path:  
   `loom init --project alpha-qa --project-path /abs/path/to/repo`  
   then `GET http://127.0.0.1:8472/api/projects/alpha-qa/graph`

**Pass:** project listed; graph non-empty (or rebuild succeeds); node detail works.

---

## 3. Agents + `loom wire` (~10 min)

1. `loom detect-agents` — lists known agents present on this machine
2. `loom wire --project alpha-qa --project-path /abs/path` — writes MCP / instruction configs
3. Register + heartbeat (CLI or inbox) → agent shows **online** in Agent Directory

**Pass:** detect/wire succeed; agent status updates live.

---

## 4. Findings / decisions / hybrid search (~10 min)

1. Drop a `finding-*.md` and a `decision-*.md` into `~/.loom/inbox/alpha-qa/`
2. Confirm files move to `.processed/`
3. Dashboard search:
   - **text** mode finds the finding
   - **hybrid** mode finds a known code symbol
4. API:  
   `GET /api/projects/alpha-qa/search?q=…&mode=text`  
   `GET /api/projects/alpha-qa/search?q=…&mode=hybrid`

**Pass:** inbox processed; both search modes return expected hits.

---

## 5. Loom Agent lifecycle (~20 min)

Requires a dashboard BYOK (DeepSeek or compatible) key in Agent settings.

1. Open Loom Agent chat for a task → suggestion chip appears **pending**
2. **Dismiss** → chip cleared; cost summary updates; dismiss same id again → **HTTP 400**
3. New suggestion → **Accept** a move action → task status changes; accept again → **HTTP 400**
4. New suggestion → **Implement** → task **Running**, assignee `loom-agent-*`; pending suggestion cleared; worker starts
5. Set process `DEEPSEEK_API_KEY` to a **different** value than the dashboard key → Implement worker still uses the **dashboard** key

**Pass:** pending lifecycle correct; no 409 Accept after Implement; BYOK wins over process env.

---

## 6. Kanban + worker (~10 min)

1. Move or create a task into **Running** (UI or API)
2. Or: `loom worker --project alpha-qa --agent loom-agent --project-path /abs/path --once --task <id>`
3. Confirm git worktree / branch `loom/task-<id>` exists
4. Task reaches **Done** with a reviewable diff; **Merge** into a throwaway target branch works

**Pass:** isolated worktree, Done + diff, merge succeeds.

---

## 7. Federation (~5 min)

1. Index a **second** project in Loom
2. Open the **Federation** tab in the dashboard
3. `GET /api/federated/stats`  
   `GET /api/federated/query?q=<shared-symbol>`

**Pass:** stats non-empty; query returns cross-project hits when symbols overlap.

---

## 8. Team auth (~10 min)

1. Stop stack; start with `./run.sh --auth-token alpha-secret`
2. Write without `Authorization: Bearer …` → rejected (e.g. create task / register)
3. Most list/read GETs still work for UI polling
4. With Bearer (or dashboard `NEXT_PUBLIC_LOOM_AUTH_TOKEN`) writes succeed; WebSocket connects with `?token=`

**Pass:** unauthenticated writes fail; authenticated writes + WS succeed.

---

## 9. Docs / install path (~5 min)

1. From a fresh checkout of the release tag, follow CHANGELOG / README install (`./run.sh --open` or `pip install -e .`)
2. Spot-check [USAGE](../USAGE.md), [API](../API.md), and [docs-site](../../docs-site/index.md) links against real UI/CLI behavior

**Pass:** documented install works; no broken primary links for shipped features.

---

## Sign-off

| Area | Pass | Fail / notes |
|------|:----:|--------------|
| 0 Automated gate | | |
| 1 run.sh bring-up | | |
| 2 Project + graph | | |
| 3 Agents + wire | | |
| 4 Findings + search | | |
| 5 Loom Agent lifecycle | | |
| 6 Kanban / worker | | |
| 7 Federation | | |
| 8 Team auth | | |
| 9 Docs install | | |

**Tester:** _______________  
**Build / tag:** _______________  
**Date:** _______________  
**Decision:** Ship / No-ship

---

## Out of scope

- Publishing `loom-os` to PyPI
- Load / soak testing
- Releasing companion packages (`loom-client`, `langchain-loom`, dashboard npm)
