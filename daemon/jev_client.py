"""TypeSafe Jev (System One) client — typed decisions, not chat."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

logger = logging.getLogger("loom.jev")

DEFAULT_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
SYSTEMONE_PATH = "/v1/systemone"
MAX_ATTEMPTS = 4
MAX_RETRY_SLEEP_SEC = 8.0
INITIAL_BACKOFF_SEC = 0.5
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class JevError(Exception):
    """Raised when the TypeSafe API call fails."""


def resolve_systemone_url(base_url: str | None = None) -> str:
    """Return a POST URL for ``/v1/systemone``.

    A bare host such as ``http://localhost:11434`` gets the path appended.
    A URL that already ends with ``/v1/systemone`` is kept (trailing slash stripped).
    """
    raw = base_url if base_url is not None else os.environ.get("TYPESAFE_BASE_URL", DEFAULT_SYSTEMONE_URL)
    url = (raw or DEFAULT_SYSTEMONE_URL).strip()
    if not url:
        url = DEFAULT_SYSTEMONE_URL
    url = url.rstrip("/")
    if url.endswith(SYSTEMONE_PATH):
        return url
    return f"{url}{SYSTEMONE_PATH}"


def _retry_delay(attempt: int, headers: Any | None) -> float:
    """Seconds to wait after a failed attempt (0-based). Caps at MAX_RETRY_SLEEP_SEC."""
    backoff = min(MAX_RETRY_SLEEP_SEC, INITIAL_BACKOFF_SEC * (2 ** attempt))
    if headers is None:
        return backoff
    raw = None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:
        raw = None
    if raw is None:
        return backoff
    try:
        return min(MAX_RETRY_SLEEP_SEC, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return backoff


class JevClient:
    """Thin HTTP client for POST /v1/systemone."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", "")
        self.base_url = resolve_systemone_url(base_url)
        self.timeout = timeout
        self._sleep = sleep if sleep is not None else time.sleep
        self.max_attempts = max(1, max_attempts)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, state: Any, questions: dict[str, dict], model: str = DEFAULT_MODEL) -> dict[str, Any]:
        """Send state + questions; return the full TypeSafe response.

        The payload includes ``answers``, ``usage``, and ``model`` when the API
        provides them. ``questions`` values are primitives:
        ``{"type": "noul"|"choice"|"score", "instructions": ..., "criteria": ...}``.
        """
        if not self.api_key:
            raise JevError("TYPESAFE_API_KEY not configured")
        body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            req = urllib.request.Request(
                self.base_url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                if not isinstance(payload, dict):
                    raise JevError("TypeSafe returned a non-object payload")
                payload.setdefault("answers", {})
                payload.setdefault("usage", {})
                return payload
            except urllib.error.HTTPError as e:
                status = getattr(e, "code", 0)
                detail = e.read().decode() if e.fp else str(e)
                headers = getattr(e, "headers", None)
                last_error = JevError(f"TypeSafe HTTP {status}: {detail}")
                if status in RETRYABLE_STATUS and attempt + 1 < self.max_attempts:
                    delay = _retry_delay(attempt, headers)
                    logger.warning(
                        "Jev HTTP %s, retrying in %.2fs (attempt %s/%s)",
                        status, delay, attempt + 1, self.max_attempts,
                    )
                    self._sleep(delay)
                    continue
                raise last_error from e
            except Exception as e:
                raise JevError(str(e)) from e
        raise last_error or JevError("TypeSafe request failed")
