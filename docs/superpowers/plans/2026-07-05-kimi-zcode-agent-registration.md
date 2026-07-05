# Kimi Code and ZCode Agent Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kimi Code and ZCode to the Loom OS built-in agent catalog with auto-detection and dashboard avatar/tooltip polish.

**Architecture:** Extend `daemon/known_agents.py` with two new catalog entries and a macOS app-bundle detector for ZCode; the existing `/api/agents/known` endpoint and `RegisterAgentModal` consume the catalog unchanged. Add a small avatar map and hover tooltips in the dashboard so the new agents are recognizable.

**Tech Stack:** Python 3.11+, pytest; Next.js 16 / React 19 / TypeScript / Tailwind CSS; JSON i18n message files.

---

## Task 1: Extend `daemon/known_agents.py`

**Files:**
- Modify: `daemon/known_agents.py`
- Create: `tests/test_known_agents.py`

### Step 1: Write the failing tests

Create `tests/test_known_agents.py`:

```python
"""Tests for the built-in agent catalog and detection helpers."""
from daemon.known_agents import KNOWN_AGENTS, detect_installed, get_known_agents


def test_catalog_includes_kimi_code_and_zcode():
    names = {a["name"] for a in get_known_agents()}
    assert "kimi-code" in names
    assert "zcode" in names


def test_kimi_code_detected_when_kimi_binary_on_path(monkeypatch):
    def fake_which(name: str):
        return "/usr/local/bin/kimi" if name == "kimi" else None

    monkeypatch.setattr("daemon.known_agents.shutil.which", fake_which)
    installed = detect_installed()
    assert installed.get("kimi-code") == "/usr/local/bin/kimi"


def test_zcode_detected_when_macos_app_bundle_present(monkeypatch):
    home = "/Users/test"

    class FakePath:
        def __init__(self, path):
            self._path = str(path)

        def __str__(self):
            return self._path

        def __fspath__(self):
            return self._path

        def exists(self):
            return self._path == "/Applications/ZCode.app"

        def __truediv__(self, other):
            sep = "" if self._path.endswith("/") else "/"
            return FakePath(f"{self._path}{sep}{other}")

        @classmethod
        def home(cls):
            return FakePath(home)

    monkeypatch.setattr("daemon.known_agents.Path", FakePath)
    installed = detect_installed()
    assert installed.get("zcode") == "/Applications/ZCode.app"


def test_zcode_detected_in_user_applications_folder(monkeypatch):
    home = "/Users/test"

    class FakePath:
        def __init__(self, path):
            self._path = str(path)

        def __str__(self):
            return self._path

        def __fspath__(self):
            return self._path

        def exists(self):
            return self._path == f"{home}/Applications/ZCode.app"

        def __truediv__(self, other):
            sep = "" if self._path.endswith("/") else "/"
            return FakePath(f"{self._path}{sep}{other}")

        @classmethod
        def home(cls):
            return FakePath(home)

    monkeypatch.setattr("daemon.known_agents.Path", FakePath)
    installed = detect_installed()
    assert installed.get("zcode") == f"{home}/Applications/ZCode.app"
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/test_known_agents.py -v
```

**Expected:** Three failures:
- `test_catalog_includes_kimi_code_and_zcode` — `AssertionError` because the names are missing.
- `test_kimi_code_detected_when_kimi_binary_on_path` — `KeyError` or `assert None == ...`.
- `test_zcode_detected_when_macos_app_bundle_present` — `assert None == ...`.

### Step 3: Implement the catalog additions

Edit `daemon/known_agents.py` and add two entries to `KNOWN_AGENTS` (after the `cursor` entry or at the end of the list):

```python
    {
        "name": "kimi-code",
        "display": "Kimi Code",
        "detect_cmd": "kimi",
        "description": "Moonshot AI's Kimi Code CLI agent",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "generation", "refactoring"],
    },
    {
        "name": "zcode",
        "display": "ZCode",
        "detect_cmd": None,
        "description": "Zhipu AI's ZCode agentic development environment",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "generation", "long-context", "review"],
    },
```

Add a ZCode app-bundle detector after `_detect_cursor`:

```python
def _detect_zcode() -> str | None:
    """Detect ZCode via its macOS app bundle."""
    zcode_app = Path("/Applications/ZCode.app")
    if zcode_app.exists():
        return str(zcode_app)
    user_zcode = Path.home() / "Applications" / "ZCode.app"
    if user_zcode.exists():
        return str(user_zcode)
    return None
```

Update `detect_installed` to call `_detect_zcode()` for the `zcode` entry:

```python
        else:
            # Special-case detection handlers
            if agent["name"] == "cursor":
                path = _detect_cursor()
                if path:
                    installed[agent["name"]] = path
            elif agent["name"] == "zcode":
                path = _detect_zcode()
                if path:
                    installed[agent["name"]] = path
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/test_known_agents.py -v
```

**Expected:** All four tests pass.

### Step 5: Commit

```bash
git add daemon/known_agents.py tests/test_known_agents.py
git commit -m "feat: add Kimi Code and ZCode to built-in agent catalog"
```

---

## Task 2: Add per-agent avatar map to `AgentCard`

**Files:**
- Modify: `dashboard/components/agent-card.tsx`

### Step 1: Add the avatar map

Inside `dashboard/components/agent-card.tsx`, after the imports and before the `AgentCard` component, add:

```typescript
const AGENT_AVATAR: Record<
  string,
  { initials: string; bg: string; text: string }
> = {
  "claude-code": { initials: "CC", bg: "bg-emerald-900", text: "text-emerald-300" },
  codex: { initials: "CX", bg: "bg-blue-900", text: "text-blue-300" },
  "kimi-code": { initials: "KM", bg: "bg-indigo-900", text: "text-indigo-300" },
  zcode: { initials: "ZC", bg: "bg-violet-900", text: "text-violet-300" },
};
```

### Step 2: Use the avatar map

Replace the existing `initials` and `avatarBg[agent.status]` logic in the component with:

```typescript
const avatar = AGENT_AVATAR[agent.agent_name] ?? {
  initials: agent.agent_name
    .split("-")
    .map((w) => w[0]?.toUpperCase())
    .join("")
    .slice(0, 2),
  bg: avatarBg[agent.status].split(" ")[0], // keep the background half
  text: avatarBg[agent.status].split(" ")[1], // keep the text half
};
```

Then update the avatar `div` className to:

```tsx
<div
  className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold text-sm ${avatar.bg} ${avatar.text}`}
>
  {avatar.initials}
</div>
```

**Before/after context:** The old className used `${avatarBg[agent.status]}` and the old initials came from the local `initials` constant. Remove the now-unused `initials` constant.

### Step 3: Verify the dashboard builds

```bash
cd dashboard && npm run build
```

**Expected:** Build completes with no TypeScript errors.

### Step 4: Commit

```bash
git add dashboard/components/agent-card.tsx
git commit -m "feat(dashboard): distinct avatars for Kimi Code and ZCode"
```

---

## Task 3: Add description tooltips to `RegisterAgentModal`

**Files:**
- Modify: `dashboard/components/register-agent-modal.tsx`

### Step 1: Add tooltips to installed-agent chips

In the `installedAgents.map(...)` button, add a `title` attribute:

```tsx
<button
  key={ka.name}
  type="button"
  onClick={() => selectKnownAgent(ka)}
  title={ka.description}
  className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
    agent === ka.name
      ? "border-emerald-600 bg-emerald-900/30 text-emerald-300"
      : "border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-zinc-600"
  }`}
>
```

### Step 2: Add tooltips to other-agent chips

In the `otherAgents.map(...)` button, add a `title` attribute:

```tsx
<button
  key={ka.name}
  type="button"
  onClick={() => selectKnownAgent(ka)}
  title={ka.description}
  className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors opacity-60 hover:opacity-100 ${
    agent === ka.name
      ? "border-zinc-600 bg-zinc-800 text-zinc-300"
      : "border-zinc-800 bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
  }`}
>
```

### Step 3: Verify the dashboard builds

```bash
cd dashboard && npm run build
```

**Expected:** Build completes with no TypeScript errors.

### Step 4: Commit

```bash
git add dashboard/components/register-agent-modal.tsx
git commit -m "feat(dashboard): show description tooltips on agent quick-pick chips"
```

---

## Task 4: Update i18n placeholders and supported-agent docs

**Files:**
- Modify: `dashboard/messages/en.json`
- Modify: `dashboard/messages/ar.json`
- Modify: `docs/AGENT-LIFECYCLE.md`

### Step 1: Update English placeholder

In `dashboard/messages/en.json`, change:

```json
"agentNamePlaceholder": "e.g. claude-code, codex",
```

to:

```json
"agentNamePlaceholder": "e.g. claude-code, codex, kimi-code, zcode",
```

### Step 2: Update Arabic placeholder

In `dashboard/messages/ar.json`, change:

```json
"agentNamePlaceholder": "مثال: claude-code, codex",
```

to:

```json
"agentNamePlaceholder": "مثال: claude-code, codex, kimi-code, zcode",
```

### Step 3: Update supported agents list

In `docs/AGENT-LIFECYCLE.md`, locate the **Supported Agents** section and append:

```markdown
- **Kimi Code** (`kimi-code`)
- **ZCode** (`zcode`)
```

The section should read:

```markdown
The worker currently integrates with:
- **Claude Code** (`claude-code`)
- **OpenAI Codex** (`codex`)
- **Kimi Code** (`kimi-code`)
- **ZCode** (`zcode`)

Additional agents can be added by implementing the filesystem protocol.
```

### Step 4: Commit

```bash
git add dashboard/messages/en.json dashboard/messages/ar.json docs/AGENT-LIFECYCLE.md
git commit -m "docs: list Kimi Code and ZCode as supported agents and update registration placeholders"
```

---

## Task 5: Final verification

**Files:**
- All files above

### Step 1: Run Python tests

```bash
pytest tests/test_known_agents.py tests/test_api.py -v
```

**Expected:** All tests pass. `test_api.py` ensures the `/api/agents/known` endpoint still merges installed flags correctly.

### Step 2: Run dashboard build

```bash
cd dashboard && npm run build
```

**Expected:** Build succeeds.

### Step 3: Manual smoke check (optional)

Start the daemon and dashboard, open a project, click **Register Agent**, and confirm:

- Kimi Code appears as a known agent.
- ZCode appears as a known agent.
- Hovering either chip shows its description tooltip.
- After registering, the agent card shows the correct mapped initials and color.

### Step 4: Commit any remaining changes

If the verification surfaced no changes, no extra commit is needed. If any fixes were made, commit them with a descriptive message.

---

## Self-review

**Spec coverage:**
- Backend catalog additions → Task 1.
- ZCode macOS app-bundle detection → Task 1, `_detect_zcode`.
- Dashboard avatar map → Task 2.
- Dashboard quick-pick tooltips → Task 3.
- i18n placeholder updates → Task 4.
- Docs update → Task 4.
- Tests → Task 1.

**Placeholder scan:** No TBD/TODO/fill-in-details. Every step includes exact file paths, exact code snippets, and exact commands.

**Type consistency:**
- `detect_installed()` still returns `dict[str, str]`.
- `AgentCard` continues to receive the same `agent` prop shape.
- `RegisterAgentModal` `KnownAgent` type already includes `description`; the tooltip uses it directly.
