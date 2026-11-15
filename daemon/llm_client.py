"""OpenAI-compatible chat client (DeepSeek default, BYOK providers)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("loom.llm")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class LlmError(Exception):
    """Raised when the chat completion call fails."""


class LlmClient:
    """Minimal chat-completions client for OpenAI-compatible APIs."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_BASE_URL, timeout: float = 120.0):
        self.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_usage: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]], model: str = DEFAULT_MODEL) -> str:
        """Return assistant content for a chat completion request."""
        if not self.api_key:
            raise LlmError("API key not configured — add it in Agent settings")
        url = f"{self.base_url}/v1/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(
            url,
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
            raise LlmError(f"LLM HTTP {e.code}: {detail}") from e
        except Exception as e:
            raise LlmError(str(e)) from e
        usage = payload.get("usage") if isinstance(payload, dict) else None
        self.last_usage = usage if isinstance(usage, dict) else None
        choices = payload.get("choices") or []
        if not choices:
            raise LlmError("LLM returned no choices")
        msg = choices[0].get("message") or {}
        return (msg.get("content") or "").strip()

    def chat_json(self, messages: list[dict[str, str]], model: str = DEFAULT_MODEL) -> dict[str, Any]:
        """Chat and parse the assistant reply as JSON (fenced blocks stripped)."""
        text = self.chat(messages, model=model)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"reply": text, "candidates": []}
