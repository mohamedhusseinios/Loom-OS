"""Jev judge request shaping for pattern_stage1 / pattern_stage2 packs (no live HTTP)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from daemon.decision import NullDecisionClient
from daemon.jev_client import JevClient

_TASK = {"title": "t", "instruction": "fix login bug", "status": "todo"}
_LEGACY = {"complete", "blocked", "ready_to_implement"}


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


def _run(pack: str, *, catalog: list[dict], candidates: list[dict], answers: dict[str, dict]):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _response({"answers": answers, "usage": {"input_tokens": 3}, "model": "jev-x"})

    with patch("daemon.jev_client.urllib.request.urlopen", side_effect=fake_urlopen):
        client = JevClient(api_key="tok", provider="typesafe", sleep=lambda _d: None)
        result = client.judge(pack=pack, task=_TASK, catalog=catalog, candidates=candidates)
    return result, captured["body"]


def test_stage1_questions_keyed_by_candidate_id() -> None:
    cands = [{"id": "type:bugfix", "label": "type = bugfix"}, {"id": "size:small", "label": "size = small"}, {"label": "no id"}]
    result, body = _run("pattern_stage1", catalog=cands, candidates=cands, answers={"type:bugfix": {"noul": 0.9}, "size:small": {"noul": 0.4}})
    assert set(body["questions"]) == {"type:bugfix", "size:small"}
    assert not _LEGACY & set(body["questions"])
    assert body["state"]["pack"] == "pattern_stage1"
    assert result.scores == {"type:bugfix": 0.9, "size:small": 0.4}
    assert not result.skipped


def test_stage2_questions_keyed_by_family_id_with_criteria_in_state() -> None:
    cat = [{"id": "debug", "name": "Debug", "when_to_use": ["bug repro"], "anti_criteria": ["greenfield"]}, {"id": "react", "when_to_use": ["small change"], "anti_criteria": []}]
    result, body = _run("pattern_stage2", catalog=cat, candidates=cat, answers={"debug": {"noul": 0.8}, "react": {"noul": 0.5}})
    assert list(body["questions"]) == ["debug", "react"]
    assert not _LEGACY & set(body["questions"])
    assert body["state"]["families"]["debug"]["anti_criteria"] == ["greenfield"]
    assert body["state"]["families"]["react"]["when_to_use"] == ["small change"]
    assert result.scores == {"debug": 0.8, "react": 0.5}


def test_stage2_falls_back_to_candidates_when_catalog_empty() -> None:
    cands = [{"id": "tdd", "when_to_use": ["tests first"]}]
    _, body = _run("pattern_stage2", catalog=[], candidates=cands, answers={"tdd": {"noul": 0.6}})
    assert list(body["questions"]) == ["tdd"]


def test_pattern_pack_without_ids_makes_no_http_call() -> None:
    with patch("daemon.jev_client.urllib.request.urlopen") as urlopen:
        result = JevClient(api_key="tok", provider="typesafe").judge(pack="pattern_stage1", task=_TASK, catalog=[], candidates=[])
    urlopen.assert_not_called()
    assert result.scores == {} and not result.skipped


def test_other_packs_keep_legacy_questions() -> None:
    _, body = _run("context", catalog=[{"id": "loom.move_ready", "label": "Ready"}], candidates=[], answers={})
    assert set(body["questions"]) == _LEGACY
    assert "catalog" in body["state"]


def test_null_client_pattern_packs_skip() -> None:
    for pack in ("pattern_stage1", "pattern_stage2"):
        result = NullDecisionClient().judge(pack=pack, task=_TASK, catalog=[{"id": "react"}], candidates=[{"id": "react"}])
        assert result.skipped and result.skip_reason == "none"
