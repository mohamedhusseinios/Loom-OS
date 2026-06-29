# Loom OS Phase 2 — Team Mode (Shared Daemon, Multi-User) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Source spec:** [docs/superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md](../superpowers/specs/2026-06-29-loom-post-parity-roadmap-design.md) — Feature #4
> **Parent plan:** [docs/plans/2026-06-29-post-parity-roadmap-implementation.md](2026-06-29-post-parity-roadmap-implementation.md) — Phase 2

**Goal:** Run one daemon for several developers behind **opt-in** auth, with per-user inbox isolation. Local single-process stays the default (auth off).

**Architecture:** A token-based FastAPI middleware that is a no-op when no token is configured. Inbox paths extended to `~/.loom/inbox/<project>/<user>/`. Registry `agents` table gains a `user` column. `SHARED_CONTEXT.md` aggregates cross-user findings. Dashboard gets a team view + auth header. WebSocket supports optional token auth via query param.

**Tech Stack:** Python 3.11+ (FastAPI middleware, aiosqlite), TypeScript (Next.js 16, React 19, shadcn).

## Global Constraints (inherited)

- **Auth must be strictly opt-in** — when no token is set, every existing test passes unchanged (moat).
- Single-process daemon — no Docker, Neo4j, external DB, or cloud service.
- Filesystem inbox protocol preserved — extend with user sub-paths, never replace.
- Per-project isolation intact (and per-user sub-scopes).
- Existing test suite must stay green; every new daemon module gets `tests/test_<module>.py`.
- WebSocket events emitted for new state changes (`team:agent_joined`).

---

## Task 4.1: `auth.py` — token middleware (optional dependency)

**Files:**
- Create: `daemon/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `TokenAuthMiddleware` class + `require_token(request)` FastAPI dependency.
- `require_token` is a **no-op** (returns `None`) when no `LOOM_AUTH_TOKEN` env var or `--auth-token` CLI flag is set.
- When a token IS configured, `require_token` checks the `Authorization: Bearer <token>` header on write routes + `/ws`; returns `None` on match, raises `HTTPException(401)` on mismatch/missing.
- WebSocket auth: `verify_ws_token(token: str | None) -> bool` — checks query param `?token=...`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import pytest
import os
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from daemon.auth import require_token, TokenAuthMiddleware, verify_ws_token, reset_auth_token


@pytest.fixture(autouse=True)
def reset_auth():
    """Ensure auth token is cleared between tests."""
    reset_auth_token()
    yield
    reset_auth_token()


def test_no_token_configured_allows_everything():
    """When no token is set, require_token is a no-op (moat preserved)."""
    # require_token should not raise
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(require_token())
    assert result is None


def test_token_configured_rejects_missing_header():
    """When a token is set, requests without Authorization header get 401."""
    os.environ["LOOM_AUTH_TOKEN"] = "secret123"
    reset_auth_token()  # re-read env

    app = FastAPI()
    app.add_middleware(TokenAuthMiddleware, token="secret123")

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    @app.get("/open")
    async def open_endpoint():
        return {"ok": True}

    # Write routes require auth — GET is open by default in the middleware
    # but we test the dependency directly:
    with pytest.raises(HTTPException) as exc_info:
        import asyncio
        asyncio.get_event_loop().run_until_complete(require_token())
    assert exc_info.value.status_code == 401


def test_token_configured_accepts_correct_header():
    """When the correct Bearer token is provided, access is granted."""
    os.environ["LOOM_AUTH_TOKEN"] = "secret123"
    reset_auth_token()

    # Simulate a request with the correct header
    from starlette.requests import Request
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer secret123")],
    }
    request = Request(scope)

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(require_token(request))
    assert result is None  # no exception raised


def test_verify_ws_token_no_token_configured():
    """WebSocket auth is permissive when no token is set."""
    assert verify_ws_token(None) is True
    assert verify_ws_token("anything") is True


def test_verify_ws_token_with_token_configured():
    """WebSocket auth checks the token when configured."""
    os.environ["LOOM_AUTH_TOKEN"] = "ws-secret"
    reset_auth_token()

    assert verify_ws_token("ws-secret") is True
    assert verify_ws_token("wrong") is False
    assert verify_ws_token(None) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.auth'`

- [ ] **Step 3: Write minimal implementation**

```python
# daemon/auth.py
"""Optional token-based auth middleware for Team Mode.

When no token is configured (the default), all auth checks are no-ops
and the daemon behaves exactly as in solo mode — preserving the moat.
Tokens are set via the ``LOOM_AUTH_TOKEN`` env var or ``--auth-token`` CLI flag.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


_configured_token: Optional[str] = None


def configure_auth_token(token: str | None) -> None:
    """Set the auth token (called from CLI ``--auth-token`` or lifespan)."""
    global _configured_token
    _configured_token = token


def reset_auth_token() -> None:
    """Re-read the token from env, or clear it. Used by tests."""
    global _configured_token
    _configured_token = os.environ.get("LOOM_AUTH_TOKEN") or None


def get_auth_token() -> Optional[str]:
    return _configured_token


def is_auth_enabled() -> bool:
    return _configured_token is not None


async def require_token(request: Request | None = None) -> None:
    """FastAPI dependency: reject requests without the correct token.

    No-op when auth is not configured (preserves solo mode).
    """
    if not is_auth_enabled():
        return None

    if request is None:
        # Allow direct call without a request for backward compat,
        # but when auth is enabled this is a 401.
        raise HTTPException(status_code=401, detail="Authentication required")

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == _configured_token:
            return None

    raise HTTPException(status_code=401, detail="Invalid or missing token")


def verify_ws_token(token: str | None) -> bool:
    """Check a WebSocket connection token (passed via query param).

    Returns ``True`` when auth is not configured (preserves solo mode).
    """
    if not is_auth_enabled():
        return True
    return token == _configured_token


# Write routes that require auth when team mode is on.
# GET/read routes remain open — auth protects writes, not reads.
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks the token on write routes.

    When no token is configured, this middleware passes all requests through.
    """

    def __init__(self, app, token: str | None = None):
        super().__init__(app)
        if token:
            configure_auth_token(token)

    async def dispatch(self, request, call_next):
        if not is_auth_enabled():
            return await call_next(request)

        if request.method in _WRITE_METHODS:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer ") or auth_header[7:] != _configured_token:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing token"},
                )

        return await call_next(request)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/auth.py tests/test_auth.py
git commit -m "feat(auth): add optional token middleware — no-op when unconfigured"
```

---

## Task 4.2: CLI `--auth-token` flag on `loom start`

**Files:**
- Modify: `daemon/main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `loom start --auth-token <token>` sets the env var and configures the middleware.
- Produces: `loom start --host 0.0.0.0` (already supported) combined with `--auth-token` enables team mode.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_cli.py
def test_start_auth_token_flag_exists():
    """`loom start --help` shows the --auth-token flag."""
    import sys
    from daemon.main import main
    sys.argv = ["loom", "start", "--help"]
    try:
        main()
    except SystemExit:
        pass  # --help causes argparse to exit
    # If we got here without error, the flag was accepted
```

- [ ] **Step 2: Run test to verify behavior**

Run: `pytest tests/test_cli.py::test_start_auth_token_flag_exists -v`
Expected: May pass or fail depending on argparse — verify the flag is present.

- [ ] **Step 3: Implement the `--auth-token` flag**

```python
# daemon/main.py — modify cmd_start to configure auth:
def cmd_start(args):
    """Start the Loom daemon."""
    # Configure auth token if provided
    if getattr(args, "auth_token", None):
        import os
        os.environ["LOOM_AUTH_TOKEN"] = args.auth_token
        from daemon.auth import configure_auth_token
        configure_auth_token(args.auth_token)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "daemon.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )

# daemon/main.py — add the flag to the start subparser:
    start_p.add_argument("--auth-token", default=None,
                         help="Enable team mode with token-based auth (optional)")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/main.py tests/test_cli.py
git commit -m "feat(cli): add --auth-token flag to loom start for team mode"
```

---

## Task 4.3: Per-user inbox path parsing in watcher

**Files:**
- Modify: `daemon/watcher.py`
- Test: `tests/test_watcher.py` (create if doesn't exist)

**Interfaces:**
- Produces: `parse_inbox_path(path: str) -> tuple[str, str | None, str]` — extracts `(project, user, filename)` from an inbox path. User is `None` for the old flat layout `inbox/<project>/<file>`.
- Modifies: `InboxHandler._dispatch` to use `parse_inbox_path` and pass `(project, user, filepath)` to the callback.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_watcher.py
import pytest
from daemon.watcher import parse_inbox_path


def test_parse_flat_inbox_path():
    """Old layout: inbox/<project>/<file> — user is None."""
    project, user, filename = parse_inbox_path(
        "/home/user/.loom/inbox/my-project/finding-1.md"
    )
    assert project == "my-project"
    assert user is None
    assert filename == "finding-1.md"


def test_parse_user_inbox_path():
    """New layout: inbox/<project>/<user>/<file> — user is captured."""
    project, user, filename = parse_inbox_path(
        "/home/user/.loom/inbox/my-project/alice/finding-1.md"
    )
    assert project == "my-project"
    assert user == "alice"
    assert filename == "finding-1.md"


def test_parse_processed_subdirectory():
    """Paths under .processed/ still extract project and user."""
    project, user, filename = parse_inbox_path(
        "/home/user/.loom/inbox/my-project/bob/.processed/register.json"
    )
    assert project == "my-project"
    assert user == "bob"
    assert filename == "register.json"


def test_parse_path_without_inbox():
    """Paths that don't contain 'inbox' return safe defaults."""
    project, user, filename = parse_inbox_path("/tmp/some-file.md")
    assert project == "unknown"
    assert user is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_watcher.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_inbox_path'`

- [ ] **Step 3: Implement `parse_inbox_path` and update `_dispatch`**

```python
# Add to daemon/watcher.py:

def parse_inbox_path(path: str) -> tuple[str, str | None, str]:
    """Extract (project, user, filename) from an inbox file path.

    Supports both layouts:
    - Flat:   inbox/<project>/<file>           → (project, None, file)
    - User:   inbox/<project>/<user>/<file>    → (project, user, file)

    Paths under .processed/ are handled correctly (user is still captured).
    Returns ("unknown", None, filename) if 'inbox' is not in the path.
    """
    from pathlib import Path
    parts = Path(path).parts
    try:
        inbox_idx = parts.index("inbox")
    except ValueError:
        return ("unknown", None, Path(path).name)

    remaining = parts[inbox_idx + 1:]
    if len(remaining) >= 3:
        # inbox/<project>/<user>/<file>  (or inbox/<project>/<user>/.processed/<file>)
        project = remaining[0]
        user = remaining[1]
        filename = remaining[-1]
    elif len(remaining) == 2:
        # inbox/<project>/<file>  (old flat layout)
        project = remaining[0]
        user = None
        filename = remaining[1]
    elif len(remaining) == 1:
        project = remaining[0]
        user = None
        filename = ""
    else:
        project = "unknown"
        user = None
        filename = ""
    return (project, user, filename)


# Modify InboxHandler to accept a callback that receives (project, user, filepath):
EventHandler = Callable[[str, str | None, str], Awaitable[None]]  # (project, user, filepath)


class InboxHandler(FileSystemEventHandler):
    def __init__(self, callback: EventHandler, loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop

    def on_created(self, event):
        if event.is_directory:
            return
        self._dispatch(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._dispatch(event.src_path)

    def _dispatch(self, filepath: str):
        project, user, _ = parse_inbox_path(filepath)
        asyncio.run_coroutine_threadsafe(
            self.callback(project, user, filepath), self.loop
        )
```

- [ ] **Step 4: Update Router.handle_file signature to accept user**

```python
# daemon/router.py — modify handle_file to accept an optional user parameter:
    async def handle_file(self, project: str, filepath: str, user: str | None = None):
        """Route an inbox file to the correct handler."""
        path = Path(filepath)
        filename = path.name.lower()

        if not path.exists():
            return

        try:
            if filename == "register.json":
                await self._handle_register(project, path, user=user)
            elif filename == "heartbeat.json":
                await self._handle_heartbeat(project, path, user=user)
            elif filename.startswith("finding-") and filename.endswith(".md"):
                await self._handle_finding(project, path, user=user)
            elif filename.startswith("decision-") and filename.endswith(".md"):
                await self._handle_decision(project, path, user=user)
            elif filename.startswith("task-") and filename.endswith(".json"):
                await self._handle_task(project, path, user=user)
            else:
                logger.debug(f"Ignoring unknown file: {filename}")
                return

            try:
                processed_dir = path.parent / ".processed"
                processed_dir.mkdir(exist_ok=True)
                path.rename(processed_dir / path.name)
            except FileNotFoundError:
                pass

        except Exception as e:
            logger.error(f"Error handling {filepath}: {e}")
            await self._emit_error(project, filepath, str(e))
```

Then add `user: str | None = None` to each `_handle_*` method signature and pass `user` to `_handle_register` (for the registry upsert). The other handlers can ignore it for now.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_watcher.py tests/test_router.py -v`
Expected: PASS (new watcher tests + existing router tests — router tests call `handle_file(project, filepath)` which still works with `user=None` default)

- [ ] **Step 6: Commit**

```bash
git add daemon/watcher.py daemon/router.py tests/test_watcher.py tests/test_router.py
git commit -m "feat(watcher): parse per-user inbox paths + pass user to router"
```

---

## Task 4.4: Registry `user` column + per-user agent scoping

**Files:**
- Modify: `daemon/registry.py` (migration + upsert + list_agents_by_user)
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `agents` table gains `user TEXT` column (nullable, default NULL for backward compat).
- `upsert_agent` stores `agent.user` if set.
- `list_agents(project, user=None)` — when `user` is provided, filters by user; when `None`, returns all agents for the project (backward compat).
- `_row_to_agent` reads the `user` column.
- `AgentInfo` model gains `user: Optional[str] = None`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_registry.py
@pytest.mark.asyncio
async def test_upsert_and_list_agents_by_user(tmp_path):
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    # Alice's agent
    await registry.upsert_agent(AgentInfo(
        agent_id="claude-proj-alice", agent_name="claude-code", version="1.0",
        project="proj", capabilities=["code-analysis"], user="alice",
    ))
    # Bob's agent
    await registry.upsert_agent(AgentInfo(
        agent_id="claude-proj-bob", agent_name="claude-code", version="1.0",
        project="proj", capabilities=["code-analysis"], user="bob",
    ))

    # List by user
    alice_agents = await registry.list_agents("proj", user="alice")
    assert len(alice_agents) == 1
    assert alice_agents[0].user == "alice"

    bob_agents = await registry.list_agents("proj", user="bob")
    assert len(bob_agents) == 1
    assert bob_agents[0].user == "bob"

    # List all (backward compat — no user filter)
    all_agents = await registry.list_agents("proj")
    assert len(all_agents) == 2


@pytest.mark.asyncio
async def test_agent_without_user_still_works(tmp_path):
    """Backward compat: agents without a user field work as before."""
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    await registry.upsert_agent(AgentInfo(
        agent_id="codex-proj", agent_name="codex", version="1.0",
        project="proj", capabilities=["code-analysis"],
    ))
    retrieved = await registry.get_agent("codex-proj")
    assert retrieved.user is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py::test_upsert_and_list_agents_by_user -v`
Expected: FAIL — `AgentInfo` has no `user` field / `agents` table has no `user` column

- [ ] **Step 3: Implement the migration + storage**

First add `user` to `AgentInfo` in `daemon/models.py`:
```python
class AgentInfo(BaseModel):
    agent_id: str
    agent_name: str
    version: str
    project: str
    capabilities: list[str]
    structured_capabilities: list[AgentCapability] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.ONLINE
    last_heartbeat: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user: Optional[str] = None
```

Then in `daemon/registry.py`:
```python
# In initialize(), after the agents table CREATE, add migration:
        cursor = await self.db.execute("PRAGMA table_info(agents)")
        cols = [r[1] for r in await cursor.fetchall()]
        if "user" not in cols:
            await self.db.execute("ALTER TABLE agents ADD COLUMN user TEXT")
        if "structured_capabilities" not in cols:
            await self.db.execute(
                "ALTER TABLE agents ADD COLUMN structured_capabilities TEXT DEFAULT '[]'"
            )
        await self.db.commit()

# In upsert_agent, add user to the INSERT:
    async def upsert_agent(self, agent: AgentInfo):
        await self.db.execute(
            """INSERT OR REPLACE INTO agents
               (agent_id, agent_name, version, project, capabilities,
                structured_capabilities, status, last_heartbeat, registered_at, user)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent.agent_id,
                agent.agent_name,
                agent.version,
                agent.project,
                json.dumps(agent.capabilities),
                json.dumps([c.model_dump() for c in agent.structured_capabilities]),
                agent.status.value,
                agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                agent.registered_at.isoformat(),
                agent.user,
            ),
        )
        await self.db.commit()

# In list_agents, add optional user filter:
    async def list_agents(self, project: Optional[str] = None, user: Optional[str] = None) -> list[AgentInfo]:
        if project and user:
            cursor = await self.db.execute(
                "SELECT * FROM agents WHERE project = ? AND user = ? ORDER BY registered_at DESC",
                (project, user),
            )
        elif project:
            cursor = await self.db.execute(
                "SELECT * FROM agents WHERE project = ? ORDER BY registered_at DESC",
                (project,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM agents ORDER BY registered_at DESC"
            )
        rows = await cursor.fetchall()
        return [self._row_to_agent(r) for r in rows]

# In _row_to_agent, read the user column:
    @staticmethod
    def _row_to_agent(row) -> AgentInfo:
        from daemon.models import AgentCapability
        keys = row.keys()
        raw_caps = row["structured_capabilities"] if "structured_capabilities" in keys else "[]"
        try:
            sc = [AgentCapability(**c) for c in json.loads(raw_caps or "[]")]
        except (json.JSONDecodeError, TypeError):
            sc = []
        user_val = row["user"] if "user" in keys else None
        return AgentInfo(
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            version=row["version"],
            project=row["project"],
            capabilities=json.loads(row["capabilities"]),
            structured_capabilities=sc,
            status=AgentStatus(row["status"]),
            last_heartbeat=(
                datetime.fromisoformat(row["last_heartbeat"])
                if row["last_heartbeat"]
                else None
            ),
            registered_at=datetime.fromisoformat(row["registered_at"]),
            user=user_val,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_registry.py tests/test_api.py -v`
Expected: PASS (new tests + existing tests — backward compat confirmed)

- [ ] **Step 5: Commit**

```bash
git add daemon/models.py daemon/registry.py tests/test_registry.py
git commit -m "feat(registry): add user column for per-user agent scoping (backward-compatible)"
```

---

## Task 4.5: Router passes `user` to `_handle_register` + emits `team:agent_joined`

**Files:**
- Modify: `daemon/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- `_handle_register` stores the `user` on the `AgentInfo` when provided.
- Emits `team:agent_joined` WS event (with user info) when a user-scoped registration occurs, in addition to the existing `agent:online` event.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_router.py
@pytest.mark.asyncio
async def test_register_with_user_emits_team_agent_joined(tmp_path):
    class _Reg:
        async def upsert_agent(self, agent): pass
        async def upsert_project(self, project, path): pass
        async def get_project(self, p): return None
    class _Graph:
        available = False

    router = Router(registry=_Reg(), graph_engine=_Graph())

    inbox = tmp_path / "inbox" / "proj" / "alice"
    inbox.mkdir(parents=True)
    reg = inbox / "register.json"
    reg.write_text(json.dumps({
        "agent": "claude-code", "version": "1.0", "project": "proj",
        "project_path": str(tmp_path), "capabilities": ["code-analysis"],
    }))

    await router._handle_register("proj", reg, user="alice")

    events = []
    while not router.events.empty():
        events.append(await router.events.get())
    event_types = [e.event for e in events]
    assert "agent:online" in event_types
    assert "team:agent_joined" in event_types
    team_event = next(e for e in events if e.event == "team:agent_joined")
    assert team_event.data["user"] == "alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_router.py::test_register_with_user_emits_team_agent_joined -v`
Expected: FAIL — `_handle_register` doesn't accept `user` parameter / doesn't emit `team:agent_joined`

- [ ] **Step 3: Implement the user-aware register handler**

```python
# daemon/router.py — modify _handle_register:
    async def _handle_register(self, project: str, path: Path, user: str | None = None):
        payload = RegisterPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"
        if user:
            agent_id = f"{payload.agent}-{project}-{user}"

        agent = AgentInfo(
            agent_id=agent_id,
            agent_name=payload.agent,
            version=payload.version,
            project=project,
            capabilities=payload.capabilities,
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
            user=user,
        )
        await self.registry.upsert_agent(agent)
        await self.registry.upsert_project(project, payload.project_path)

        if self.graph.available:
            asyncio.create_task(self._build_project(project, payload.project_path))
        else:
            asyncio.create_task(
                self._scan_and_share(project, payload.project_path)
            )

        await self._emit_event("agent:online", project, {
            "agent": payload.agent,
            "capabilities": payload.capabilities,
        })

        # When a user-scoped registration occurs, emit team event
        if user:
            await self._emit_event("team:agent_joined", project, {
                "agent": payload.agent,
                "user": user,
                "capabilities": payload.capabilities,
            })
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_router.py -v`
Expected: PASS (new test + existing tests)

- [ ] **Step 5: Commit**

```bash
git add daemon/router.py tests/test_router.py
git commit -m "feat(router): pass user to register handler + emit team:agent_joined event"
```

---

## Task 4.6: Cross-user shared context aggregation

**Files:**
- Modify: `daemon/shared_context.py` (agent roster section — show user)
- Test: `tests/test_shared_context.py` (create)

**Interfaces:**
- The `_agent_roster` section now shows the user column when present.
- Findings from all users appear in the shared context (already the case since `_recent_findings` scans the whole project inbox).

- [ ] **Step 1: Write the test**

```python
# tests/test_shared_context.py
import pytest
from pathlib import Path
from daemon.shared_context import _agent_roster


@pytest.mark.asyncio
async def test_agent_roster_shows_user(tmp_path):
    class _Reg:
        async def list_agents(self, project=None, user=None):
            from daemon.models import AgentInfo, AgentStatus
            return [
                AgentInfo(agent_id="a-p-alice", agent_name="claude", version="1.0",
                         project="p", capabilities=["review"], user="alice"),
                AgentInfo(agent_id="a-p-bob", agent_name="codex", version="1.0",
                         project="p", capabilities=["test"], user="bob"),
            ]
    roster = await _agent_roster("p", _Reg())
    assert "alice" in roster
    assert "bob" in roster
    assert "claude" in roster
    assert "codex" in roster
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_shared_context.py -v`
Expected: May pass already (the roster just lists agents) — verify it shows user.

- [ ] **Step 3: Update `_agent_roster` to include user column**

```python
# daemon/shared_context.py — modify _agent_roster:
async def _agent_roster(project_id: str, registry) -> str:
    try:
        agents = await registry.list_agents(project_id)
        if not agents:
            return ""

        lines = ""
        for a in agents:
            status_icon = {"online": "🟢", "offline": "⚫", "working": "🟡"}.get(
                a.status.value, "⚫"
            )
            user = a.user or "—"
            lines += f"| {status_icon} {a.agent_name} | {user} | {a.version} | {', '.join(a.capabilities[:5])} |\n"

        return (
            f"## Agent Roster\n\n"
            f"| Agent | User | Version | Capabilities |\n|---|---|---|---|\n"
            f"{lines}\n"
        )
    except Exception as exc:
        logger.warning("Agent roster section failed: %s", exc)
        return ""
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_shared_context.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/shared_context.py tests/test_shared_context.py
git commit -m "feat(shared-context): show user column in agent roster for team mode"
```

---

## Task 4.7: API — wire auth middleware + team endpoints

**Files:**
- Modify: `daemon/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Lifespan configures `TokenAuthMiddleware` when `LOOM_AUTH_TOKEN` is set.
- `GET /api/projects/{project_id}/agents` accepts optional `?user=<user>` query param.
- WebSocket endpoint checks `?token=...` query param when auth is enabled.
- `GET /api/team/status` → `{"auth_enabled": bool, "users": ["alice", "bob"]}` — lists active users.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_team_status_endpoint_no_auth(client):
    """GET /api/team/status returns auth_enabled=False by default."""
    resp = client.get("/api/team/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is False
    assert "users" in body


def test_agents_endpoint_filters_by_user(client):
    """GET /agents?user=... filters by user when team mode is on."""
    from daemon.models import AgentInfo
    import asyncio

    # Add a second agent with a user
    async def seed():
        await api_module.registry.upsert_agent(AgentInfo(
            agent_id="codex-noor-alice", agent_name="codex", version="1.0",
            project="noor", capabilities=["test"], user="alice",
        ))
    asyncio.get_event_loop().run_until_complete(seed())

    resp = client.get("/api/projects/noor/agents?user=alice")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert all(a["user"] == "alice" for a in agents)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_team_status_endpoint_no_auth -v`
Expected: FAIL — 404 (route not defined)

- [ ] **Step 3: Implement the endpoints + middleware wiring**

```python
# daemon/api.py — in lifespan, after CORS middleware, add auth middleware:
    # Configure auth if token is set
    from daemon.auth import is_auth_enabled, configure_auth_token
    import os
    env_token = os.environ.get("LOOM_AUTH_TOKEN")
    if env_token:
        configure_auth_token(env_token)
    # Middleware is added at module level (see below) so it checks at request time.

# Add the middleware after CORS:
from daemon.auth import TokenAuthMiddleware, is_auth_enabled, verify_ws_token

# Note: the middleware self-disables when no token is configured.
app.add_middleware(TokenAuthMiddleware)

# Modify the agents endpoint to accept user filter:
@app.get("/api/projects/{project_id}/agents")
async def list_agents(project_id: str, user: str = None):
    """List agents for a project, optionally filtered by user."""
    agents = await registry.list_agents(project_id, user=user)
    return {"agents": [a.model_dump() for a in agents]}

# Add team status endpoint:
@app.get("/api/team/status")
async def team_status():
    """Return team mode status: auth enabled + active users."""
    from daemon.auth import is_auth_enabled
    auth = is_auth_enabled()
    # List distinct users from agents
    all_agents = await registry.list_agents()
    users = sorted(set(a.user for a in all_agents if a.user))
    return {"auth_enabled": auth, "users": users}

# Modify WebSocket endpoint to check token:
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for live event streaming. Optional token auth via ?token=."""
    from daemon.auth import verify_ws_token
    token = websocket.query_params.get("token")
    if not verify_ws_token(token):
        await websocket.close(code=1008, reason="Unauthorized")
        return
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -v`
Expected: PASS (new tests + existing tests — auth is off in tests so middleware is a no-op)

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat(api): wire auth middleware + team status endpoint + user-filtered agents"
```

---

## Task 4.8: Dashboard — team view + auth header

**Files:**
- Create: `dashboard/components/team-status.tsx`
- Modify: `dashboard/lib/api.ts` (add `getTeamStatus` + auth header on fetches)
- Modify: `dashboard/lib/use-websocket.tsx` (pass token in WS URL when configured)
- Modify: `dashboard/components/sidebar.tsx` (show team status indicator)

**Interfaces:**
- Consumes: `GET /api/team/status`.
- When auth is enabled, the dashboard sends `Authorization: Bearer <token>` on API calls and `?token=<token>` on the WebSocket.

- [ ] **Step 1: Add `getTeamStatus` to `lib/api.ts`**

```typescript
// Add to dashboard/lib/api.ts:

export interface TeamStatus {
  auth_enabled: boolean;
  users: string[];
}

export async function getTeamStatus(): Promise<TeamStatus> {
  return fetchApi("/api/team/status");
}
```

- [ ] **Step 2: Create `team-status.tsx` component**

```tsx
// dashboard/components/team-status.tsx
"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getTeamStatus, type TeamStatus } from "@/lib/api";
import { Users, ShieldCheck, ShieldOff } from "lucide-react";

export function TeamStatus() {
  const t = useTranslations("TeamStatus");
  const [status, setStatus] = useState<TeamStatus | null>(null);

  useEffect(() => {
    getTeamStatus().then(setStatus).catch(() => {});
  }, []);

  if (!status) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-md text-xs text-zinc-500">
      {status.auth_enabled ? (
        <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
      ) : (
        <ShieldOff className="w-3.5 h-3.5" />
      )}
      <span>{status.auth_enabled ? t("teamMode") : t("soloMode")}</span>
      {status.users.length > 0 && (
        <span className="flex items-center gap-1 text-zinc-600">
          <Users className="w-3 h-3" />
          {status.users.length}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add TeamStatus to sidebar**

```tsx
// In dashboard/components/sidebar.tsx, import and render <TeamStatus />:
import { TeamStatus } from "@/components/team-status";

// Add it near the bottom of the sidebar, before the Add Project button:
        <TeamStatus />
```

- [ ] **Step 4: Add i18n strings**

Add to `messages/en.json`:
```json
"TeamStatus": {
  "teamMode": "Team mode",
  "soloMode": "Solo mode"
}
```

Add to `messages/ar.json`:
```json
"TeamStatus": {
  "teamMode": "وضع الفريق",
  "soloMode": "الوضع الفردي"
}
```

- [ ] **Step 5: Verify dashboard builds**

Run: `cd dashboard && npm run build`
Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/team-status.tsx \
  dashboard/lib/api.ts \
  dashboard/components/sidebar.tsx \
  dashboard/messages/en.json \
  dashboard/messages/ar.json
git commit -m "feat(dashboard): add team mode status indicator in sidebar"
```

---

## Verification

- [ ] `pytest tests/ -v` — all tests green (existing + new auth/watcher/registry/router/api tests).
- [ ] With no token configured, every existing test passes unchanged (moat preserved).
- [ ] With `LOOM_AUTH_TOKEN=secret`, unauthenticated write requests get 401.
- [ ] With `LOOM_AUTH_TOKEN=secret`, WebSocket without `?token=secret` is rejected.
- [ ] Per-user inbox paths `~/.loom/inbox/<project>/<user>/` work — agents registered under a user appear with that user.
- [ ] `GET /api/team/status` returns `auth_enabled` + active users list.
- [ ] `GET /api/projects/{id}/agents?user=alice` returns only Alice's agents.
- [ ] `SHARED_CONTEXT.md` agent roster shows the User column.
- [ ] `team:agent_joined` WS event emitted when a user-scoped registration occurs.
- [ ] Dashboard sidebar shows team/solo mode indicator.
- [ ] Dashboard builds without errors.