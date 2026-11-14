"""Unit tests for Jev and LLM clients with mocked HTTP."""
import io
import json
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest
import urllib.error

from daemon.jev_client import (
    JevClient, JevError, resolve_systemone_url, _retry_delay, MAX_RETRY_SLEEP_SEC,
)
from daemon.llm_client import LlmClient, LlmError


def _http_error(code: int, body: bytes = b"err", retry_after=None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone", code, "error", headers, io.BytesIO(body),
    )


def _ok_response(payload: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_resolve_systemone_url_appends_path_to_bare_host():
    assert resolve_systemone_url("http://localhost:11434") == "http://localhost:11434/v1/systemone"
    assert resolve_systemone_url("http://localhost:11434/") == "http://localhost:11434/v1/systemone"
    assert resolve_systemone_url("https://api.typesafe.ai") == "https://api.typesafe.ai/v1/systemone"


def test_resolve_systemone_url_keeps_full_endpoint():
    full = "https://api.typesafe.ai/v1/systemone"
    assert resolve_systemone_url(full) == full
    assert resolve_systemone_url(full + "/") == full


def test_jev_client_uses_resolved_base_url():
    client = JevClient(api_key="tok", base_url="http://localhost:11434")
    assert client.base_url == "http://localhost:11434/v1/systemone"


def test_jev_ask_returns_full_response():
    payload = {
        "model": "jev-1.14.0",
        "answers": {"urgency": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 120, "output_tokens": 12},
    }
    with patch("daemon.jev_client.urllib.request.urlopen", return_value=_ok_response(payload)):
        client = JevClient(api_key="tok")
        result = client.ask("state", {"urgency": {"type": "noul", "instructions": "urgent?"}})
    assert result["answers"]["urgency"]["noul"] == 0.9
    assert result["usage"]["input_tokens"] == 120
    assert result["model"] == "jev-1.14.0"


def test_jev_missing_key_raises():
    client = JevClient(api_key="")
    with pytest.raises(JevError):
        client.ask("x", {"q": {"type": "noul", "instructions": "y"}})


def test_jev_retries_429_then_succeeds():
    sleeps: list[float] = []
    payload = {"answers": {"q": {"type": "noul", "noul": 0.8}}, "usage": {"input_tokens": 10}}
    side_effect = [
        _http_error(429, b"rate", retry_after=0.25),
        _ok_response(payload),
    ]
    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=side_effect):
        client = JevClient(api_key="tok", sleep=sleeps.append)
        result = client.ask("s", {"q": {"type": "noul", "instructions": "x"}})
    assert result["answers"]["q"]["noul"] == 0.8
    assert sleeps == [0.25]


def test_jev_retries_503_with_backoff_then_gives_up():
    sleeps: list[float] = []
    side_effect = [_http_error(503, b"down") for _ in range(4)]
    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=side_effect):
        client = JevClient(api_key="tok", sleep=sleeps.append, max_attempts=4)
        with pytest.raises(JevError, match="HTTP 503"):
            client.ask("s", {"q": {"type": "noul", "instructions": "x"}})
    assert sleeps == [0.5, 1.0, 2.0]


def test_jev_does_not_retry_400():
    sleeps: list[float] = []
    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=_http_error(400, b"bad")):
        client = JevClient(api_key="tok", sleep=sleeps.append)
        with pytest.raises(JevError, match="HTTP 400"):
            client.ask("s", {"q": {"type": "noul", "instructions": "x"}})
    assert sleeps == []


def test_retry_after_is_capped():
    headers = Message()
    headers["Retry-After"] = "99"
    assert _retry_delay(0, headers) == MAX_RETRY_SLEEP_SEC


def test_llm_chat_parses_content():
    payload = {"choices": [{"message": {"content": "  hello  "}}], "usage": {"prompt_tokens": 4, "completion_tokens": 1}}
    with patch("daemon.llm_client.urllib.request.urlopen", return_value=_ok_response(payload)):
        client = LlmClient(api_key="sk")
        text = client.chat([{"role": "user", "content": "hi"}])
    assert text == "hello"
    assert client.last_usage["prompt_tokens"] == 4
    assert client.last_usage["completion_tokens"] == 1


def test_llm_missing_key_raises():
    client = LlmClient(api_key="")
    with pytest.raises(LlmError):
        client.chat([{"role": "user", "content": "hi"}])
