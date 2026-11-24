"""Token-based authentication middleware (strictly opt-in).

When no token is configured, every function here is a no-op / permissive.
Auth becomes active only when ``configure_auth_token(token)`` is called
(e.g. by the CLI ``--auth-token`` flag) or when ``LOOM_AUTH_TOKEN`` is set
in the environment.

When auth is enabled, all ``/api/*`` routes require a Bearer token except
``/api/health``. Short-lived WebSocket tickets (from ``POST /api/ws-ticket``)
are accepted on the WS query string in place of the long-lived team secret.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Module-level state ---------------------------------------------------------

_configured_token: Optional[str] = None
_token_resolved: bool = False

# short-lived WS tickets: token -> expiry monotonic
_ws_tickets: dict[str, float] = {}
_ws_tickets_lock = threading.Lock()
WS_TICKET_TTL_S = 120.0


def configure_auth_token(token: Optional[str]):
    """Set the auth token in memory (``None`` disables auth)."""
    global _configured_token, _token_resolved
    _configured_token = token
    _token_resolved = True


def reset_auth_token():
    """Re-read the token from the ``LOOM_AUTH_TOKEN`` env var."""
    global _configured_token, _token_resolved
    _configured_token = os.environ.get("LOOM_AUTH_TOKEN") or None
    _token_resolved = True


def get_auth_token() -> Optional[str]:
    """Return the configured token (or ``None`` if auth is disabled)."""
    if not _token_resolved:
        reset_auth_token()
    return _configured_token


def is_auth_enabled() -> bool:
    """Return ``True`` when a token is configured (auth is active)."""
    return get_auth_token() is not None


def _tokens_match(provided: str, expected: str) -> bool:
    """Constant-time compare; unequal lengths still fail safely."""
    if len(provided) != len(expected):
        secrets.compare_digest(provided, provided)
        return False
    return secrets.compare_digest(provided, expected)


def issue_ws_ticket() -> str:
    """Issue a short-lived ticket for WebSocket connect (auth must be on)."""
    ticket = secrets.token_urlsafe(32)
    expiry = time.monotonic() + WS_TICKET_TTL_S
    with _ws_tickets_lock:
        _ws_tickets[ticket] = expiry
        # prune expired
        now = time.monotonic()
        dead = [k for k, exp in _ws_tickets.items() if exp <= now]
        for k in dead:
            _ws_tickets.pop(k, None)
    return ticket


def _consume_ws_ticket(ticket: str) -> bool:
    with _ws_tickets_lock:
        exp = _ws_tickets.pop(ticket, None)
    if exp is None:
        return False
    return exp > time.monotonic()


# --- FastAPI dependency / WebSocket helper ----------------------------------


async def require_token(request: Request = None):  # type: ignore[assignment]
    """FastAPI dependency: no-op when auth disabled, 401 when enabled + bad token.

    When used as ``Depends(require_token)``, FastAPI injects the current
    :class:`Request`.  When called directly with ``None`` (no request), the
    function raises 401 if auth is enabled because no header can be checked.
    """
    token = get_auth_token()
    if token is None:
        return  # auth disabled — permissive
    auth_header = ""
    if request is not None:
        auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided = auth_header[7:]
    else:
        provided = auth_header
    if not _tokens_match(provided, token):
        raise HTTPException(status_code=401, detail="Invalid or missing auth token")


def verify_ws_token(token: Optional[str]) -> bool:
    """WebSocket token check — permissive when auth disabled.

    Accepts the long-lived team token or a one-time short-lived ticket.
    """
    configured = get_auth_token()
    if configured is None:
        return True  # auth disabled
    if not token:
        return False
    if _tokens_match(token, configured):
        return True
    return _consume_ws_ticket(token)


# --- ASGI middleware --------------------------------------------------------


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer on all ``/api/*`` when auth is enabled.

    ``GET /api/health`` stays open for probes. ``OPTIONS`` is left open so
    CORS preflight can succeed. When auth is disabled this is a no-op.
    """

    _PUBLIC_PATHS = frozenset({"/api/health"})

    async def dispatch(self, request: Request, call_next):
        if not is_auth_enabled():
            return await call_next(request)

        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in self._PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]
        else:
            provided = auth_header

        expected = get_auth_token()
        if expected is None or not _tokens_match(provided, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing auth token"},
            )

        return await call_next(request)


# Initialise from env on module load so the middleware works without an
# explicit ``configure_auth_token()`` call.
reset_auth_token()
