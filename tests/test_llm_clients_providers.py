"""OpenAI-compatible and Anthropic Loom Agent LLM clients."""
import io
import json
import threading
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

import pytest
import urllib.error
import urllib.request

from daemon.llm_client import AnthropicLlmClient, LlmClient, LlmError, build_llm_client, list_remote_models


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_build_llm_client_picks_anthropic():
    client = build_llm_client("sk", "https://api.anthropic.com", "anthropic")
    assert isinstance(client, AnthropicLlmClient)
    client = build_llm_client("sk", "https://api.openai.com", "openai")
    assert isinstance(client, LlmClient)


def test_list_remote_models_openai(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        assert req.get_method() == "GET"
        assert req.full_url.endswith("/v1/models")
        assert req.headers.get("Authorization") == "Bearer sk-oai"
        return _FakeResp({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})

    monkeypatch.setattr("daemon.llm_client._open_http", fake_urlopen)
    models = list_remote_models("sk-oai", "https://api.openai.com", "openai")
    assert models == ["gpt-4o", "gpt-4o-mini"]


def test_list_remote_models_anthropic(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        assert req.get_header("X-api-key") == "sk-ant"
        assert req.get_header("Anthropic-version")
        return _FakeResp({"data": [{"id": "claude-sonnet-4-5"}]})

    monkeypatch.setattr("daemon.llm_client._open_http", fake_urlopen)
    models = list_remote_models("sk-ant", "https://api.anthropic.com", "anthropic")
    assert models == ["claude-sonnet-4-5"]


def test_anthropic_chat_maps_system_and_usage(monkeypatch):
    def fake_urlopen(req, timeout=120.0):
        body = json.loads(req.data.decode())
        assert body["model"] == "claude-sonnet-4-5"
        assert body["system"] == "sys"
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert req.get_header("X-api-key") == "sk-ant"
        return _FakeResp({
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        })

    monkeypatch.setattr("daemon.llm_client._open_http", fake_urlopen)
    client = AnthropicLlmClient(api_key="sk-ant")
    text = client.chat([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ], model="claude-sonnet-4-5")
    assert text == "hello"
    assert client.last_usage["prompt_tokens"] == 3
    assert client.last_usage["completion_tokens"] == 2


def test_list_remote_models_requires_key():
    with pytest.raises(LlmError):
        list_remote_models("", "https://api.openai.com")


def test_http_error_omits_response_body(monkeypatch):
    def fake_open(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 401, "unauthorized", Message(), io.BytesIO(b"echo sk-secret-body"),
        )

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    with pytest.raises(LlmError) as exc:
        list_remote_models("sk-secret", "https://api.openai.com")
    assert str(exc.value) == "LLM HTTP 401"
    assert "sk-secret" not in str(exc.value)
    assert "echo" not in str(exc.value)


def test_list_remote_models_does_not_follow_redirects():
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/stolen")
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        with pytest.raises(LlmError, match="LLM HTTP 302"):
            list_remote_models("sk-live", f"http://127.0.0.1:{port}", timeout=2.0)
    finally:
        thread.join(timeout=2)
        server.server_close()
    assert seen == ["/v1/models"]


def test_redirect_handler_refuses_cross_host():
    from daemon import llm_client

    handler = llm_client._NoRedirect()
    req = urllib.request.Request("https://api.openai.com/v1/models", headers={"Authorization": "Bearer sk-secret"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(req, None, 302, "found", Message(), "http://169.254.169.254/latest")
    assert exc.value.code == 302
    assert "sk-secret" not in str(exc.value)


def test_sync_providers_drops_omitted_custom():
    from daemon.agent_credentials import sync_providers_on_update

    current = [
        {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]},
        {"id": "custom-x", "name": "X", "base_url": "http://x", "model_ids": ["m"], "api_style": "openai"},
    ]
    incoming = [
        {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]},
    ]
    providers, removed = sync_providers_on_update(current, incoming)
    assert "custom-x" in removed
    assert all(p["id"] != "custom-x" for p in providers)
    assert any(p["id"] == "deepseek" for p in providers)


def test_openai_chat_stream_yields_content_deltas(monkeypatch):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    class _StreamResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise AssertionError("stream should iterate lines, not read()")

        def __iter__(self):
            return iter(chunks)

    def fake_open(req, timeout=120.0):
        body = json.loads(req.data.decode())
        assert body["stream"] is True
        return _StreamResp()

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    client = LlmClient(api_key="sk-test")
    events = list(client.chat_stream([{"role": "user", "content": "hi"}], model="m"))
    texts = [(e.kind, e.text) for e in events]
    assert ("content", "Hel") in texts
    assert ("content", "lo") in texts
    assert ("reasoning", "think") in texts
    assert client.last_reasoning_content == "think"


def test_anthropic_chat_stream_yields_text_deltas(monkeypatch):
    chunks = [
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n',
        b'data: {"type":"message_stop"}\n\n',
    ]

    class _StreamResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter(chunks)

    def fake_open(req, timeout=120.0):
        body = json.loads(req.data.decode())
        assert body["stream"] is True
        return _StreamResp()

    monkeypatch.setattr("daemon.llm_client._open_http", fake_open)
    client = AnthropicLlmClient(api_key="sk-ant")
    events = list(client.chat_stream([{"role": "user", "content": "x"}], model="claude-sonnet-4-5"))
    assert [(e.kind, e.text) for e in events] == [("content", "Hi")]
