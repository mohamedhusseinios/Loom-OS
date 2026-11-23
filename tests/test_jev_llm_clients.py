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
from daemon.llm_client import LlmClient, LlmError, build_llm_client, resolve_chat_completions_url


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
    assert client.available is False
    assert client.timeout == 10.0
    with pytest.raises(JevError):
        client.ask("x", {"q": {"type": "noul", "instructions": "y"}})


def test_ollama_ask_without_key_omits_authorization():
    payload = {"answers": {"q": {"type": "noul", "noul": 0.4}}, "usage": {}}
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        captured["timeout"] = timeout
        return _ok_response(payload)

    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=fake_urlopen):
        client = JevClient(api_key="", provider="ollama", base_url="http://127.0.0.1:11434", model="nimble")
        result = client.ask("state", {"q": {"type": "noul", "instructions": "x"}}, model="nimble")
    assert client.available is True
    assert client.timeout == 5.0
    assert captured["auth"] is None
    assert captured["timeout"] == 5.0
    assert result["answers"]["q"]["noul"] == 0.4


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
    with patch("daemon.llm_client._open_http", return_value=_ok_response(payload)):
        client = LlmClient(api_key="sk")
        text = client.chat([{"role": "user", "content": "hi"}])
    assert text == "hello"
    assert client.last_usage["prompt_tokens"] == 4
    assert client.last_usage["completion_tokens"] == 1


def test_llm_missing_key_raises():
    client = LlmClient(api_key="")
    with pytest.raises(LlmError):
        client.chat([{"role": "user", "content": "hi"}])


def test_resolve_chat_completions_url_appends_v1_to_bare_host():
    assert resolve_chat_completions_url("https://api.deepseek.com") == "https://api.deepseek.com/v1/chat/completions"
    assert resolve_chat_completions_url("https://api.deepseek.com/") == "https://api.deepseek.com/v1/chat/completions"


def test_resolve_chat_completions_url_does_not_double_v1():
    assert resolve_chat_completions_url("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1/chat/completions"
    assert resolve_chat_completions_url("https://api.groq.com/openai/v1") == "https://api.groq.com/openai/v1/chat/completions"
    assert resolve_chat_completions_url("http://localhost:11434/v1/") == "http://localhost:11434/v1/chat/completions"
    full = "http://localhost:1234/v1/chat/completions"
    assert resolve_chat_completions_url(full) == full
    assert resolve_chat_completions_url(full + "/") == full


def test_llm_custom_root_posts_single_v1_and_keyless_omits_auth():
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _ok_response({"choices": [{"message": {"content": "ok"}}], "usage": {}})

    with patch("daemon.llm_client._open_http", side_effect=fake_urlopen):
        client = build_llm_client("", "http://localhost:9000/v1", allow_missing_key=True)
        assert client.available is True
        assert client.chat([{"role": "user", "content": "hi"}], model="llama") == "ok"
    assert captured["url"] == "http://localhost:9000/v1/chat/completions"
    assert captured["auth"] is None


def test_llm_deepseek_without_key_stays_unavailable():
    client = build_llm_client("", "https://api.deepseek.com")
    assert client.available is False
    with pytest.raises(LlmError, match="API key"):
        client.chat([{"role": "user", "content": "hi"}])


def test_llm_chat_captures_reasoning_content(monkeypatch):
    class FakeResp:
        def read(self):
            return (
                b'{"choices":[{"message":{"role":"assistant","content":"hi",'
                b'"reasoning_content":"step-a"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
            )
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("daemon.llm_client._open_http", lambda *a, **k: FakeResp())
    client = LlmClient(api_key="sk")
    assert client.chat([{"role": "user", "content": "hi"}]) == "hi"
    assert client.last_reasoning_content == "step-a"


def test_llm_chat_distills_when_content_empty(monkeypatch):
    bodies = [
        b'{"choices":[{"message":{"role":"assistant","content":"",'
        b'"reasoning_content":"only reasoning answer"}}],"usage":{}}',
        b'{"choices":[{"message":{"role":"assistant","content":"Final answer."}}],'
        b'"usage":{}}',
    ]
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(*a, **k):
        i = calls["n"]
        calls["n"] += 1
        return FakeResp(bodies[min(i, len(bodies) - 1)])

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    client = LlmClient(api_key="sk")
    assert client.chat([{"role": "user", "content": "hi"}]) == "Final answer."
    assert client.last_reasoning_content == "only reasoning answer"
    assert calls["n"] == 2
