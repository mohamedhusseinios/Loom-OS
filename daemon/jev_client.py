"""TypeSafe Jev (System One) client — typed decisions, not chat."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("loom.jev")

TYPESAFE_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1/systemone")
DEFAULT_MODEL = "jev-latest"


class JevError(Exception):
    """Raised when the TypeSafe API call fails."""


class JevClient:
    """Thin HTTP client for POST /v1/systemone."""

    def __init__(self, api_key: str | None = None, base_url: str = TYPESAFE_URL, timeout: float = 30.0):
        self.api_key = api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", "")
        self.base_url = base_url
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, state: Any, questions: dict[str, dict], model: str = DEFAULT_MODEL) -> dict[str, Any]:
        """Send state + questions; return the ``answers`` map.

        ``questions`` values are primitives: ``{"type": "noul"|"choice"|"score", ...}``.
        """
        if not self.api_key:
            raise JevError("TYPESAFE_API_KEY not configured")
        body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
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
        except urllib.error.HTTPError as e:
            detail = e.read().decode() if e.fp else str(e)
            raise JevError(f"TypeSafe HTTP {e.code}: {detail}") from e
        except Exception as e:
            raise JevError(str(e)) from e
        return payload.get("answers") or {}
