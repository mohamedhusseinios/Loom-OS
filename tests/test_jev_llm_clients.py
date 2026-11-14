"""Unit tests for Jev and LLM clients with mocked HTTP."""
import json
from unittest.mock import MagicMock, patch

import pytest

from daemon.jev_client import JevClient, JevError
from daemon.llm_client import LlmClient, LlmError


def test_jev_ask_parses_answers():
    payload = {"answers": {"urgency": {"type": "noul", "noul": 0.9}}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("daemon.jev_client.urllib.request.urlopen", return_value=mock_resp):
        client = JevClient(api_key="tok")
        answers = client.ask("state", {"urgency": {"type": "noul", "instructions": "urgent?"}})
    assert answers["urgency"]["noul"] == 0.9


def test_jev_missing_key_raises():
    client = JevClient(api_key="")
    with pytest.raises(JevError):
        client.ask("x", {"q": {"type": "noul", "instructions": "y"}})


def test_llm_chat_parses_content():
    payload = {"choices": [{"message": {"content": "  hello  "}}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("daemon.llm_client.urllib.request.urlopen", return_value=mock_resp):
        client = LlmClient(api_key="sk")
        text = client.chat([{"role": "user", "content": "hi"}])
    assert text == "hello"


def test_llm_missing_key_raises():
    client = LlmClient(api_key="")
    with pytest.raises(LlmError):
        client.chat([{"role": "user", "content": "hi"}])
