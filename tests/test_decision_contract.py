"""Shared DecisionClient contract tests — Null, Jev (typesafe/ollama), and GLiClass."""
import io
import json
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest
import urllib.error

from daemon.decision import DecisionResult, NullDecisionClient
from daemon.gliclass_client import GLiClassClient, resolve_gliclass_url
from daemon.jev_client import JevClient


@pytest.fixture
def null_client() -> NullDecisionClient:
    return NullDecisionClient()


def test_null_judge_returns_skipped_none_provider(null_client: NullDecisionClient):
    result = null_client.judge(pack="context", task=None, catalog=[], candidates=[])
    assert isinstance(result, DecisionResult)
    assert result.skipped is True
    assert result.skip_reason == "none"
    assert result.provider == "none"
    assert result.model == ""
    assert result.scores == {}
    assert result.usage.input_tokens is None
    assert result.latency_ms >= 0


def test_null_filter_relevance_returns_skipped_none_provider(null_client: NullDecisionClient):
    result = null_client.filter_relevance(pack="context", task=None, catalog=[], hits=[])
    assert result.skipped is True
    assert result.skip_reason == "none"
    assert result.provider == "none"
    assert result.usage.input_tokens is None
    assert result.latency_ms >= 0


def _http_error(code: int, body: bytes = b"err") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://decision.test", code, "error", Message(), io.BytesIO(body))


def _body_response(raw: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _ok_response(payload: dict | list) -> MagicMock:
    return _body_response(json.dumps(payload).encode())


def _task() -> dict:
    return {"title": "Ship filter", "instruction": "Rank graph hits", "status": "ready"}


def _hits() -> list[dict]:
    return [{"id": "node-a", "label": "auth"}, {"id": "node-b", "label": "billing"}]


def _jev_client(provider: str, api_key: str, base_url: str | None, model: str, **kwargs: object) -> JevClient:
    return JevClient(api_key=api_key, base_url=base_url, provider=provider, model=model, sleep=lambda _delay: None, **kwargs)


_JEV_CASES = [
    ("typesafe", "tok", None, "jev-latest", 10.0),
    ("ollama", "", "http://127.0.0.1:11434", "nimble", 5.0),
]


@pytest.mark.parametrize("provider,api_key,base_url,model,timeout", _JEV_CASES)
def test_jev_filter_shape_latency_and_ignores_unknown_keys(provider, api_key, base_url, model, timeout):
    payload = {"model": model, "answers": {"rel_0": {"type": "noul", "noul": 0.91}, "other": {"type": "noul", "noul": 0.1}}, "usage": {"input_tokens": 12, "output_tokens": 3}}
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _ok_response(payload)

    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=fake_urlopen):
        client = _jev_client(provider, api_key, base_url, model)
        assert client.timeout == timeout
        assert client.available is True
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    assert isinstance(result, DecisionResult)
    assert result.skipped is False
    assert result.skip_reason is None
    assert result.provider == provider
    assert result.model == model
    assert result.scores == {"rel_0": 0.91}
    assert "rel_1" not in result.scores
    assert "other" not in result.scores
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 3
    assert result.latency_ms >= 0
    assert captured["timeout"] == timeout
    body = json.loads(captured["req"].data.decode())
    assert set(body["questions"]) == {"rel_0", "rel_1"}
    assert body["model"] == model
    auth = captured["req"].get_header("Authorization")
    if provider == "ollama":
        assert auth is None
        assert captured["req"].full_url == "http://127.0.0.1:11434/v1/systemone"
    else:
        assert auth == "Bearer tok"


@pytest.mark.parametrize("provider,api_key,base_url,model,timeout", _JEV_CASES)
def test_jev_judge_shape(provider, api_key, base_url, model, timeout):
    del timeout
    payload = {"model": model, "answers": {"complete": {"noul": 0.1}, "blocked": {"noul": 0.2}, "ready_to_implement": {"noul": 0.8}}, "usage": {"input_tokens": 4}}
    with patch("daemon.jev_client.urllib.request.urlopen", return_value=_ok_response(payload)):
        client = _jev_client(provider, api_key, base_url, model)
        result = client.judge(pack="context", task=_task(), catalog=[{"id": "loom.move_ready", "label": "Ready"}], candidates=[])
    assert result.skipped is False
    assert result.provider == provider
    assert result.scores == {"complete": 0.1, "blocked": 0.2, "ready_to_implement": 0.8}
    assert result.usage.input_tokens == 4
    assert result.latency_ms >= 0


@pytest.mark.parametrize("provider,api_key,base_url,model,timeout", _JEV_CASES)
def test_jev_http_error_skips(provider, api_key, base_url, model, timeout):
    del timeout
    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=_http_error(503)):
        client = _jev_client(provider, api_key, base_url, model, max_attempts=1)
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    assert result.skipped is True
    assert result.skip_reason == "error"
    assert result.scores == {}
    assert result.provider == provider
    assert result.model == model
    assert result.latency_ms >= 0


@pytest.mark.parametrize("provider,api_key,base_url,model,timeout", _JEV_CASES)
def test_jev_timeout_skips(provider, api_key, base_url, model, timeout):
    del timeout
    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=urllib.error.URLError(TimeoutError("timed out"))):
        client = _jev_client(provider, api_key, base_url, model)
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    assert result.skipped is True
    assert result.skip_reason == "timeout"
    assert result.scores == {}
    assert result.latency_ms >= 0


@pytest.mark.parametrize("provider,api_key,base_url,model,timeout", _JEV_CASES)
def test_jev_bad_json_skips(provider, api_key, base_url, model, timeout):
    del timeout
    with patch("daemon.jev_client.urllib.request.urlopen", return_value=_body_response(b"not-json")):
        client = _jev_client(provider, api_key, base_url, model)
        result = client.judge(pack="context", task=_task(), catalog=[], candidates=[])
    assert result.skipped is True
    assert result.skip_reason == "bad_payload"
    assert result.scores == {}
    assert result.latency_ms >= 0


def test_jev_non_object_payload_is_bad_payload():
    with patch("daemon.jev_client.urllib.request.urlopen", return_value=_ok_response([])):
        client = _jev_client("typesafe", "tok", None, "jev-latest")
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    assert result.skip_reason == "bad_payload"


def test_jev_filter_retries_then_returns_scores():
    sleeps: list[float] = []
    payload = {"answers": {"rel_0": {"noul": 0.7}}, "usage": {"input_tokens": 1}}
    side_effect = [_http_error(503), _ok_response(payload)]
    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=side_effect):
        client = JevClient(api_key="tok", provider="typesafe", sleep=sleeps.append, max_attempts=2)
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=[_hits()[0]])
    assert sleeps == [0.5]
    assert result.skipped is False
    assert result.scores == {"rel_0": 0.7}


def test_typesafe_filter_without_key_skips_without_http():
    with patch("daemon.jev_client.urllib.request.urlopen") as urlopen:
        client = JevClient(api_key="", provider="typesafe")
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    urlopen.assert_not_called()
    assert client.available is False
    assert result.skipped is True
    assert result.skip_reason == "error"


def test_resolve_gliclass_url_appends_path():
    assert resolve_gliclass_url("http://127.0.0.1:8090") == "http://127.0.0.1:8090/gliclass"
    assert resolve_gliclass_url("http://127.0.0.1:8090/gliclass/") == "http://127.0.0.1:8090/gliclass"
    assert resolve_gliclass_url("") == ""


def test_gliclass_module_does_not_import_torch():
    from pathlib import Path
    import daemon.gliclass_client as gliclass_client

    source = Path(gliclass_client.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith(("import torch", "from torch", "import gliclass", "from gliclass"))


def test_gliclass_filter_posts_knowledgator_shape():
    captured: list[tuple] = []

    def fake_urlopen(req, timeout=None):
        captured.append((req, timeout))
        text = json.loads(req.data.decode())["texts"][0]
        score = 0.81 if "node-a" in text else 0.22
        return _ok_response([{"label": "relevant", "score": score}, {"label": "not_relevant", "score": 1 - score}])

    with patch("daemon.gliclass_client.urllib.request.urlopen", side_effect=fake_urlopen):
        client = GLiClassClient(base_url="http://127.0.0.1:8090", model="gliclass-edge")
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    assert client.timeout == 5.0
    assert result.skipped is False
    assert result.skip_reason is None
    assert result.provider == "gliclass"
    assert result.model == "gliclass-edge"
    assert result.scores == {"rel_0": 0.81, "rel_1": 0.22}
    assert result.usage.input_tokens is None
    assert result.latency_ms >= 0
    assert len(captured) == 2
    req, timeout = captured[0]
    assert timeout == 5.0
    assert req.full_url == "http://127.0.0.1:8090/gliclass"
    body = json.loads(req.data.decode())
    assert set(body) == {"texts", "labels", "threshold"}
    assert body["labels"] == ["relevant", "not_relevant"]
    assert body["threshold"] == 0.0
    assert isinstance(body["texts"], list) and len(body["texts"]) == 1


def test_gliclass_filter_runs_hits_concurrently():
    import threading
    import time as time_mod

    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_urlopen(req, timeout=None):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time_mod.sleep(0.05)
        with lock:
            active -= 1
        text = json.loads(req.data.decode())["texts"][0]
        score = 0.9 if "node-a" in text else 0.1
        return _ok_response([{"label": "relevant", "score": score}])

    hits = [{"id": "node-a", "label": "A"}, {"id": "node-b", "label": "B"}, {"id": "node-c", "label": "C"}]
    with patch("daemon.gliclass_client.urllib.request.urlopen", side_effect=fake_urlopen):
        client = GLiClassClient(base_url="http://127.0.0.1:8090", model="gliclass-edge")
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=hits)
    assert result.skipped is False
    assert result.scores == {"rel_0": 0.9, "rel_1": 0.1, "rel_2": 0.1}
    assert peak >= 2


def test_gliclass_missing_relevant_label_omits_score():
    with patch("daemon.gliclass_client.urllib.request.urlopen", return_value=_ok_response([{"label": "not_relevant", "score": 0.4}])):
        client = GLiClassClient(base_url="http://127.0.0.1:8090", model="gliclass-edge")
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=[_hits()[0]])
    assert result.skipped is False
    assert result.scores == {}


@pytest.mark.parametrize("side_effect,raw,reason", [
    (_http_error(500), None, "error"),
    (urllib.error.URLError(TimeoutError("timed out")), None, "timeout"),
    (None, b"not-json", "bad_payload"),
    (None, b"{\"label\": \"relevant\"}", "bad_payload"),
])
def test_gliclass_filter_errors(side_effect, raw, reason):
    if raw is not None:
        opener = patch("daemon.gliclass_client.urllib.request.urlopen", return_value=_body_response(raw))
    else:
        opener = patch("daemon.gliclass_client.urllib.request.urlopen", side_effect=side_effect)
    with opener:
        client = GLiClassClient(base_url="http://127.0.0.1:8090", model="gliclass-edge")
        result = client.filter_relevance(pack="context", task=_task(), catalog=[], hits=_hits())
    assert result.skipped is True
    assert result.skip_reason == reason
    assert result.scores == {}
    assert result.provider == "gliclass"
    assert result.model == "gliclass-edge"
    assert result.latency_ms >= 0


def test_gliclass_judge_is_unsupported_without_http():
    with patch("daemon.gliclass_client.urllib.request.urlopen") as urlopen:
        client = GLiClassClient(base_url="http://127.0.0.1:8090", model="gliclass-edge")
        result = client.judge(pack="context", task=_task(), catalog=[], candidates=[{"id": "custom.step", "graph_ids": ["node-a"]}])
    urlopen.assert_not_called()
    assert result.skipped is True
    assert result.skip_reason == "unsupported"
    assert result.provider == "gliclass"
    assert result.model == "gliclass-edge"
    assert result.scores == {}
    assert result.usage.input_tokens is None
    assert result.latency_ms >= 0