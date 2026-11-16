"""OpenAI-compatible and Anthropic Loom Agent LLM clients."""
import json
from unittest.mock import MagicMock, patch

import pytest

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

    monkeypatch.setattr("daemon.llm_client.urllib.request.urlopen", fake_urlopen)
    models = list_remote_models("sk-oai", "https://api.openai.com", "openai")
    assert models == ["gpt-4o", "gpt-4o-mini"]


def test_list_remote_models_anthropic(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        assert req.get_header("X-api-key") == "sk-ant"
        assert req.get_header("Anthropic-version")
        return _FakeResp({"data": [{"id": "claude-sonnet-4-5"}]})

    monkeypatch.setattr("daemon.llm_client.urllib.request.urlopen", fake_urlopen)
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

    monkeypatch.setattr("daemon.llm_client.urllib.request.urlopen", fake_urlopen)
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
