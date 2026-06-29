"""Tests for token-based auth middleware (Feature #4 — Team Mode)."""

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from daemon.auth import (
    configure_auth_token,
    get_auth_token,
    is_auth_enabled,
    require_token,
    reset_auth_token,
    verify_ws_token,
)


@pytest.fixture(autouse=True)
def _reset_token():
    """Ensure auth state is clean before and after every test."""
    configure_auth_token(None)
    yield
    configure_auth_token(None)


# --- require_token ----------------------------------------------------------


@pytest.mark.asyncio
async def test_no_token_configured_require_token_is_noop():
    """When no token is configured, require_token should not raise."""
    configure_auth_token(None)
    assert is_auth_enabled() is False
    await require_token(None)  # should not raise


@pytest.mark.asyncio
async def test_token_configured_raises_401_without_header():
    """Token configured + no request (no header) → HTTPException 401."""
    configure_auth_token("secret")
    assert is_auth_enabled() is True
    with pytest.raises(HTTPException) as exc:
        await require_token(None)
    assert exc.value.status_code == 401


def test_token_configured_passes_with_correct_bearer_header():
    """Token configured + correct Bearer header → 200."""
    configure_auth_token("secret")
    app = FastAPI()

    @app.get("/protected")
    async def protected(_=Depends(require_token)):
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/protected", headers={"Authorization": "Bearer secret"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_token_configured_fails_with_wrong_bearer():
    """Token configured + wrong Bearer header → 401."""
    configure_auth_token("secret")
    app = FastAPI()

    @app.get("/protected")
    async def protected(_=Depends(require_token)):
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


def test_token_configured_fails_without_header():
    """Token configured + no Authorization header → 401."""
    configure_auth_token("secret")
    app = FastAPI()

    @app.get("/protected")
    async def protected(_=Depends(require_token)):
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/protected")
    assert res.status_code == 401


# --- verify_ws_token --------------------------------------------------------


def test_verify_ws_token_permissive_when_no_token():
    """verify_ws_token returns True for anything when auth disabled."""
    configure_auth_token(None)
    assert verify_ws_token("anything") is True
    assert verify_ws_token(None) is True


def test_verify_ws_token_strict_when_token_set():
    """verify_ws_token returns True only for the matching token."""
    configure_auth_token("secret")
    assert verify_ws_token("secret") is True
    assert verify_ws_token("wrong") is False
    assert verify_ws_token(None) is False


# --- reset_auth_token -------------------------------------------------------


def test_reset_auth_token_reads_from_env(monkeypatch):
    """reset_auth_token re-reads from LOOM_AUTH_TOKEN env var."""
    monkeypatch.setenv("LOOM_AUTH_TOKEN", "env-token")
    reset_auth_token()
    assert get_auth_token() == "env-token"
    assert is_auth_enabled() is True


def test_reset_auth_token_clears_when_env_unset(monkeypatch):
    """reset_auth_token with no env var → token is None, auth disabled."""
    monkeypatch.delenv("LOOM_AUTH_TOKEN", raising=False)
    reset_auth_token()
    assert get_auth_token() is None
    assert is_auth_enabled() is False