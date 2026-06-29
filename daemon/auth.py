"""Token-based authentication middleware (strictly opt-in).

When no token is configured, every function here is a no-op / permissive.
Auth becomes active only when ``configure_auth_token(token)`` is called
(e.g. by the CLI ``--auth-token`` flag) or when ``LOOM_AUTH_TOKEN`` is set
in the environment.
"""

import os
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Module-level state ---------------------------------------------------------

_configured_token: Optional[str] = None
_token_resolved: bool = False


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
    if provided != token:
        raise HTTPException(status_code=401, detail="Invalid or missing auth token")


def verify_ws_token(token: Optional[str]) -> bool:
    """WebSocket token check — permissive when auth disabled."""
    configured = get_auth_token()
    if configured is None:
        return True  # auth disabled
    return token == configured


# --- ASGI middleware --------------------------------------------------------


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks the token on write methods.

    Read methods (``GET``, ``OPTIONS``, ``HEAD``) are always allowed so the
    dashboard continues to work without a token.  When auth is disabled the
    middleware is a complete no-op — the moat.
    """

    _WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def dispatch(self, request: Request, call_next):
        if not is_auth_enabled():
            return await call_next(request)

        if request.method.upper() not in self._WRITE_METHODS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]
        else:
            provided = auth_header

        if provided != get_auth_token():
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing auth token"},
            )

        return await call_next(request)


# Initialise from env on module load so the middleware works without an
# explicit ``configure_auth_token()`` call.
reset_auth_token()