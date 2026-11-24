"""OpenAI-compatible and Anthropic chat clients for Loom Agent BYOK providers."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Protocol

from daemon.agent_credentials import (
    API_STYLE_ANTHROPIC,
    API_STYLE_OPENAI,
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    normalize_api_style,
)

logger = logging.getLogger("loom.llm")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib forwards Authorization across hosts. Never follow that.
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _open_http(req: urllib.request.Request, timeout: float):
    return _NO_REDIRECT_OPENER.open(req, timeout=timeout)


DEFAULT_BASE_URL = DEFAULT_DEEPSEEK_BASE_URL
DEFAULT_MODEL = DEFAULT_DEEPSEEK_MODEL
ANTHROPIC_VERSION = "2023-06-01"
_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
_V1_SUFFIX = "/v1"


class LlmError(Exception):
    """Raised when the chat completion call fails."""


@dataclass(frozen=True)
class StreamDelta:
    """One incremental fragment of a streamed assistant turn."""

    kind: Literal["reasoning", "content"]
    text: str


def _iter_sse_json(resp: Any) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON objects from ``data:`` lines of an SSE response; stops at ``[DONE]``."""
    for raw in resp:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data:
            continue
        if data == "[DONE]":
            return
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def resolve_chat_completions_url(base_url: str) -> str:
    """Return a POST URL for ``/v1/chat/completions``.

    A bare host such as ``https://api.deepseek.com`` gets ``/v1`` inserted.
    A root that already ends in ``/v1`` (OpenRouter, Groq, LM Studio, Ollama)
    or in ``/chat/completions`` is not doubled.
    """
    url = (base_url or "").strip().rstrip("/")
    if url.endswith(_CHAT_COMPLETIONS_SUFFIX):
        return url
    if url.endswith(_V1_SUFFIX):
        return f"{url}{_CHAT_COMPLETIONS_SUFFIX}"
    return f"{url}{_V1_SUFFIX}{_CHAT_COMPLETIONS_SUFFIX}"


class LlmClientProtocol(Protocol):
    api_key: str
    base_url: str
    last_usage: dict[str, Any] | None

    @property
    def available(self) -> bool: ...

    def chat(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> str: ...

    def chat_json(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> dict[str, Any]: ...

    def chat_stream(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> Iterator[StreamDelta]: ...


def history_with_reasoning(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy chat turns for the provider, preserving assistant ``reasoning_content`` when present."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role") or "user"
        item: dict[str, Any] = {"role": role, "content": msg.get("content") or ""}
        reasoning = msg.get("reasoning_content")
        if role == "assistant" and isinstance(reasoning, str) and reasoning:
            item["reasoning_content"] = reasoning
        out.append(item)
    return out


_THINKING_STARTS = (
    "the user wants",
    "the user said",
    "the user is asking",
    "the user asked",
    "let me ",
    "i need to ",
    "i should ",
    "actually, i",
    "looking at the",
    "based on the shared context",
)


def looks_like_chain_of_thought(text: str) -> bool:
    """True when text reads as internal planning monologue, not a user-facing answer."""
    t = (text or "").strip().lower()
    if not t:
        return False
    head = t[:280]
    if any(head.startswith(p) for p in _THINKING_STARTS):
        return True
    if "let me " in head and any(w in head for w in ("read ", "explore", "check ", "find ", "look at", "gather")):
        return True
    return False


_DISTILL_PROMPT = (
    "Write ONLY the final answer for the user based on that reasoning. "
    "Do not narrate your process, do not say what you will do next, "
    "and do not mention tools or reading files. Be direct and useful."
)


def _safe_http_error_detail(exc: urllib.error.HTTPError, limit: int = 240) -> str:
    """Return a short provider error body with credential-looking substrings stripped."""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    text = " ".join(raw.split())
    for marker in ("Bearer ", "sk-", "x-api-key", "api_key", "authorization"):
        if marker.lower() in text.lower():
            return ""
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _http_json(url: str, *, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 120.0) -> Any:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with _open_http(req, timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = _safe_http_error_detail(e)
        raise LlmError(f"LLM HTTP {e.code}" + (f": {detail}" if detail else "")) from e
    except json.JSONDecodeError as e:
        raise LlmError("LLM returned invalid JSON") from e
    except LlmError:
        raise
    except Exception as e:
        raise LlmError(str(e)) from e


def _parse_chat_json(text: str) -> dict[str, Any]:
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


def _split_system_messages(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    converted: list[dict[str, str]] = []
    for msg in messages:
        role = msg.get("role") or "user"
        content = msg.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role not in ("user", "assistant"):
            role = "user"
        converted.append({"role": role, "content": content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, converted


def _extract_model_ids(payload: Any) -> list[str]:
    models: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    mid = item.get("id")
                    if isinstance(mid, str) and mid.strip():
                        models.append(mid.strip())
                elif isinstance(item, str) and item.strip():
                    models.append(item.strip())
        elif isinstance(payload.get("models"), list):
            for item in payload["models"]:
                if isinstance(item, dict):
                    mid = item.get("id") or item.get("name")
                    if isinstance(mid, str) and mid.strip():
                        models.append(mid.strip())
                elif isinstance(item, str) and item.strip():
                    models.append(item.strip())
    return sorted(set(models))


def list_remote_models(api_key: str, base_url: str, api_style: str = API_STYLE_OPENAI, timeout: float = 30.0) -> list[str]:
    """Fetch model ids from an OpenAI-compatible or Anthropic ``/v1/models`` endpoint."""
    if not api_key:
        raise LlmError("API key not configured — add it in Agent settings")
    style = normalize_api_style(api_style)
    root = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{root}/v1/models"
    if style == API_STYLE_ANTHROPIC:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
    else:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    payload = _http_json(url, method="GET", headers=headers, timeout=timeout)
    models = _extract_model_ids(payload)
    if not models:
        raise LlmError("Provider returned no models")
    return models


class LlmClient:
    """Minimal chat-completions client for OpenAI-compatible APIs."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_BASE_URL, timeout: float = 120.0, *, allow_missing_key: bool = False):
        self.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.allow_missing_key = allow_missing_key
        self.last_usage: dict[str, Any] | None = None
        self.last_reasoning_content: str | None = None
        self.api_style = API_STYLE_OPENAI

    @property
    def available(self) -> bool:
        return bool(self.api_key) or self.allow_missing_key

    def _chat_once(self, messages: list[dict[str, Any]], model: str) -> tuple[str, str | None]:
        """One completion call. Returns ``(content, reasoning_content)``."""
        if not self.api_key and not self.allow_missing_key:
            raise LlmError("API key not configured — add it in Agent settings")
        url = resolve_chat_completions_url(self.base_url)
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = _http_json(
            url,
            method="POST",
            body=body,
            headers=headers,
            timeout=self.timeout,
        )
        usage = payload.get("usage") if isinstance(payload, dict) else None
        self.last_usage = usage if isinstance(usage, dict) else None
        choices = payload.get("choices") or []
        if not choices:
            raise LlmError("LLM returned no choices")
        msg = choices[0].get("message") or {}
        reasoning = msg.get("reasoning_content")
        reasoning_s = reasoning if isinstance(reasoning, str) and reasoning.strip() else None
        content = (msg.get("content") or "").strip()
        return content, reasoning_s

    def _distill_final_reply(self, messages: list[dict[str, Any]], reasoning: str, model: str) -> str:
        """Ask the model for a user-facing answer after a reasoning-only (or CoT) turn."""
        follow = history_with_reasoning(messages) + [
            {"role": "assistant", "content": "", "reasoning_content": reasoning},
            {"role": "user", "content": _DISTILL_PROMPT},
        ]
        content, _extra = self._chat_once(follow, model)
        self.last_reasoning_content = reasoning
        if content and not looks_like_chain_of_thought(content):
            return content
        logger.warning("distill pass still returned empty or chain-of-thought")
        return ""

    def chat(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> str:
        """Return a user-facing assistant reply (never dumps chain-of-thought)."""
        content, reasoning = self._chat_once(messages, model)
        self.last_reasoning_content = reasoning
        # Some providers put the monologue in content and leave reasoning empty.
        if content and looks_like_chain_of_thought(content) and not reasoning:
            reasoning = content
            self.last_reasoning_content = content
            content = ""
        elif content and looks_like_chain_of_thought(content) and reasoning:
            # Prefer stored reasoning; content is also CoT — distill.
            content = ""
        if content:
            return content
        if reasoning:
            return self._distill_final_reply(messages, reasoning, model)
        return ""

    def chat_stream(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> Iterator[StreamDelta]:
        """Stream reasoning/content deltas; distill a final reply when only reasoning arrived."""
        if not self.api_key and not self.allow_missing_key:
            raise LlmError("API key not configured — add it in Agent settings")
        url = resolve_chat_completions_url(self.base_url)
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "stream": True,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict[str, Any] | None = None
        self.last_usage = None
        self.last_reasoning_content = None
        try:
            with _open_http(req, self.timeout) as resp:
                for obj in _iter_sse_json(resp):
                    chunk_usage = obj.get("usage")
                    if isinstance(chunk_usage, dict):
                        usage = chunk_usage
                    choices = obj.get("choices") or []
                    if not choices or not isinstance(choices[0], dict):
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning_piece = delta.get("reasoning_content")
                    if isinstance(reasoning_piece, str) and reasoning_piece:
                        reasoning_parts.append(reasoning_piece)
                        yield StreamDelta("reasoning", reasoning_piece)
                    content_piece = delta.get("content")
                    if isinstance(content_piece, str) and content_piece:
                        content_parts.append(content_piece)
                        yield StreamDelta("content", content_piece)
        except urllib.error.HTTPError as e:
            detail = _safe_http_error_detail(e)
            raise LlmError(f"LLM HTTP {e.code}" + (f": {detail}" if detail else "")) from e
        except LlmError:
            raise
        except Exception as e:
            raise LlmError(str(e)) from e
        self.last_usage = usage
        reasoning = "".join(reasoning_parts)
        self.last_reasoning_content = reasoning if reasoning.strip() else None
        if not "".join(content_parts).strip() and self.last_reasoning_content:
            distilled = self._distill_final_reply(messages, self.last_reasoning_content, model)
            if distilled:
                yield StreamDelta("content", distilled)

    def chat_json(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> dict[str, Any]:
        """Chat and parse the assistant reply as JSON (fenced blocks stripped)."""
        return _parse_chat_json(self.chat(messages, model=model))


class AnthropicLlmClient:
    """Anthropic Messages API client with the same surface as ``LlmClient``."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_ANTHROPIC_BASE_URL, timeout: float = 120.0):
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_usage: dict[str, Any] | None = None
        self.last_reasoning_content: str | None = None
        self.api_style = API_STYLE_ANTHROPIC

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> str:
        if not self.api_key:
            raise LlmError("API key not configured — add it in Agent settings")
        self.last_reasoning_content = None
        system, converted = _split_system_messages(messages)
        if not converted:
            converted = [{"role": "user", "content": ""}]
        body_obj: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": converted,
        }
        if system:
            body_obj["system"] = system
        url = f"{self.base_url}/v1/messages"
        payload = _http_json(
            url,
            method="POST",
            body=json.dumps(body_obj).encode(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            # Normalize to OpenAI-ish keys used by cost reporting when present.
            self.last_usage = {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        else:
            self.last_usage = None
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, list) or not content:
            raise LlmError("LLM returned no content")
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(t for t in texts if t).strip()

    def chat_stream(self, messages: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> Iterator[StreamDelta]:
        """Stream text deltas from the Anthropic Messages API (SSE)."""
        if not self.api_key:
            raise LlmError("API key not configured — add it in Agent settings")
        self.last_usage = None
        self.last_reasoning_content = None
        system, converted = _split_system_messages(messages)
        if not converted:
            converted = [{"role": "user", "content": ""}]
        body_obj: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": converted,
            "stream": True,
        }
        if system:
            body_obj["system"] = system
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(body_obj).encode(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with _open_http(req, self.timeout) as resp:
                for obj in _iter_sse_json(resp):
                    if obj.get("type") != "content_block_delta":
                        continue
                    delta = obj.get("delta") or {}
                    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
                        continue
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        yield StreamDelta("content", text)
        except urllib.error.HTTPError as e:
            detail = _safe_http_error_detail(e)
            raise LlmError(f"LLM HTTP {e.code}" + (f": {detail}" if detail else "")) from e
        except LlmError:
            raise
        except Exception as e:
            raise LlmError(str(e)) from e

    def chat_json(self, messages: list[dict[str, str]], model: str = DEFAULT_MODEL) -> dict[str, Any]:
        return _parse_chat_json(self.chat(messages, model=model))


def build_llm_client(api_key: str, base_url: str, api_style: str = API_STYLE_OPENAI, timeout: float = 120.0, *, allow_missing_key: bool = False) -> LlmClient | AnthropicLlmClient:
    style = normalize_api_style(api_style)
    if style == API_STYLE_ANTHROPIC:
        return AnthropicLlmClient(api_key=api_key, base_url=base_url or DEFAULT_ANTHROPIC_BASE_URL, timeout=timeout)
    return LlmClient(api_key=api_key, base_url=base_url or DEFAULT_BASE_URL, timeout=timeout, allow_missing_key=allow_missing_key)
