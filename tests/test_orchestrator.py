"""Orchestrator catalog merge, judgments, mid-band filter, and auto-suggest escalation."""
import pytest

from daemon.decision import DecisionResult, DecisionUsage, NullDecisionClient
from daemon.models import AgentTaskCreatePayload, AgentTaskRecord, AgentTaskStatus
from daemon.orchestrator import (
    Orchestrator, merge_catalog, loom_catalog_for_status, SuggestResult,
    Judgments, map_judgments_to_action, partition_relevance, NOUL_YES,
    template_reply, build_context_pack, context_hash, clear_filter_cache,
    select_relevant_hits,
)
from daemon.jev_client import JevClient
from daemon.llm_client import LlmClient


def test_merge_catalog_drops_uncited_candidates():
    loom = [{"id": "loom.move_ready", "label": "Ready", "source": "loom"}]
    pb = [{"id": "play.a", "label": "A", "source": "playbook"}]
    cands = [
        {"id": "x", "label": "X", "graph_ids": ["n1"]},
        {"id": "y", "label": "Y"},  # no citation
    ]
    merged = merge_catalog(loom, pb, cands)
    ids = [m["id"] for m in merged]
    assert ids == ["loom.move_ready", "play.a", "x"]


def test_loom_catalog_filters_by_status():
    ready = loom_catalog_for_status(AgentTaskStatus.READY.value)
    assert any(a["id"] == "loom.move_running" for a in ready)
    assert not any(a["id"] == "loom.move_archived" for a in ready)


@pytest.mark.asyncio
async def test_empty_graph_short_circuit(tmp_path):
    class FakeGE:
        async def hybrid_query(self, *a, **k):
            return []

    task = AgentTaskRecord(
        id="t1", project="p", title="T", instruction="do thing",
        status=AgentTaskStatus.TODO, created_at="now", updated_at="now",
    )
    orch = Orchestrator(
        FakeGE(),
        jev=JevClient(api_key=""),
        llm=LlmClient(api_key=""),
    )
    result = await orch.run_suggest_cycle(str(tmp_path), "p", task)
    assert isinstance(result, SuggestResult)
    assert result.graph_empty is True
    assert "graph" in result.reply.lower()


def test_partition_relevance_keeps_yes_and_mid_band():
    scored = [
        (0.9, {"id": "a"}),
        (0.55, {"id": "b"}),
        (0.2, {"id": "c"}),
        (0.8, {"id": "d"}),
    ]
    selected, mid, keys = partition_relevance(scored)
    assert [h["id"] for h in selected] == ["a", "d", "b"]
    assert [h["id"] for h in mid] == ["b"]
    assert keys  # mid-band is tracked
    assert "c" not in [h["id"] for h in selected]


def test_partition_relevance_falls_back_when_all_low():
    scored = [(0.1, {"id": "a"}), (0.05, {"id": "b"}), (0.0, {"id": "c"}), (0.2, {"id": "d"})]
    selected, mid, keys = partition_relevance(scored)
    assert [h["id"] for h in selected] == ["a", "b", "c", "d"]
    assert mid == []
    assert keys == []


def _catalog(status: str):
    return loom_catalog_for_status(status)


def test_map_todo_ready_when_clearly_ready():
    d = map_judgments_to_action(
        "todo",
        Judgments(complete=0.1, blocked=0.1, ready_to_implement=0.91),
        _catalog("todo"),
    )
    assert d.action_id == "loom.move_ready"
    assert d.confidence == 0.91
    assert d.uncertain is False


def test_map_todo_blocked_wins_over_ready():
    d = map_judgments_to_action(
        "todo",
        Judgments(complete=0.1, blocked=0.88, ready_to_implement=0.8),
        _catalog("todo"),
    )
    assert d.action_id == "loom.move_blocked"
    assert d.confidence == 0.88


def test_map_ready_to_running():
    d = map_judgments_to_action(
        "ready",
        Judgments(complete=0.05, blocked=0.1, ready_to_implement=0.84),
        _catalog("ready"),
    )
    assert d.action_id == "loom.move_running"
    assert d.confidence == 0.84
    assert d.uncertain is False


def test_map_running_complete_to_done():
    d = map_judgments_to_action(
        "running",
        Judgments(complete=0.93, blocked=0.05, ready_to_implement=0.2),
        _catalog("running"),
    )
    assert d.action_id == "loom.move_done"
    assert d.confidence == 0.93


def test_map_mid_band_is_uncertain():
    d = map_judgments_to_action(
        "ready",
        Judgments(complete=0.1, blocked=0.2, ready_to_implement=0.55),
        _catalog("ready"),
    )
    assert d.action_id == "loom.move_running"
    assert d.confidence == 0.55
    assert d.uncertain is True
    assert "ready_to_implement" in d.mid_band_keys


def test_map_blocked_unblocks_when_ready():
    d = map_judgments_to_action(
        "blocked",
        Judgments(complete=0.1, blocked=0.1, ready_to_implement=0.86),
        _catalog("blocked"),
    )
    assert d.action_id == "loom.move_ready"
    assert d.confidence == 0.86


def test_map_blocked_still_blocked_falls_back_uncertain():
    catalog = _catalog("blocked") + [{"id": "play.wait", "label": "Wait", "source": "playbook"}]
    d = map_judgments_to_action(
        "blocked",
        Judgments(complete=0.1, blocked=0.9, ready_to_implement=0.2),
        catalog,
    )
    # No safe loom move while clearly blocked; first catalog item, uncertain.
    assert d.uncertain is True
    assert d.action_id in {c["id"] for c in catalog}


def test_map_prefers_grounded_candidate_on_fallback():
    catalog = _catalog("todo") + [
        {"id": "custom.step", "label": "Write tests", "source": "llm", "graph_ids": ["n1"]}
    ]
    d = map_judgments_to_action(
        "todo",
        Judgments(
            complete=0.1, blocked=0.1, ready_to_implement=0.1,
            candidates=[{"id": "custom.step", "label": "Write tests", "noul": 0.81}],
        ),
        catalog,
    )
    assert d.action_id == "custom.step"
    assert d.confidence == 0.81


def test_confidence_uses_noul_not_concentration_placeholder():
    d = map_judgments_to_action(
        "running",
        Judgments(complete=0.77, blocked=0.05, ready_to_implement=0.1),
        _catalog("running"),
    )
    assert d.confidence == 0.77
    assert d.confidence != 0.5


def _task(status=AgentTaskStatus.TODO, title="T", instruction="do thing"):
    return AgentTaskRecord(
        id="t1", project="p", title=title, instruction=instruction,
        status=status, created_at="now", updated_at="now",
    )


class FakeGE:
    def __init__(self, hits=None):
        self.hits = hits if hits is not None else [
            {"id": "n1", "label": "AuthService"},
            {"id": "n2", "label": "Router"},
        ]

    async def hybrid_query(self, *a, **k):
        return list(self.hits)


class FakeDecision:
    def __init__(self, rel=None, complete=0.1, blocked=0.1, ready=0.9, grounded=None, usage=11, provider="typesafe", model="jev-latest", extra_scores=None, omit_missing=True):
        self.provider = provider
        self.model = model
        self.rel = rel if rel is not None else {"rel_0": 0.9, "rel_1": 0.2}
        self.complete = complete
        self.blocked = blocked
        self.ready = ready
        self.grounded = grounded or {}
        self.usage = usage
        self.extra_scores = dict(extra_scores or {})
        self.omit_missing = omit_missing
        self.filter_calls: list[dict] = []
        self.judge_calls: list[dict] = []

    def filter_relevance(self, *, pack, task, catalog, hits, **kwargs):
        self.filter_calls.append({"pack": pack, "task": task, "catalog": catalog, "hits": hits})
        scores = dict(self.extra_scores)
        for index, _hit in enumerate((hits or [])[:12]):
            key = f"rel_{index}"
            if key in self.rel:
                scores[key] = self.rel[key]
            elif not self.omit_missing:
                scores[key] = 0.0
        return self._result(scores)

    def judge(self, *, pack, task, catalog, candidates, **kwargs):
        self.judge_calls.append({"pack": pack, "task": task, "catalog": catalog, "candidates": candidates})
        scores = {"complete": self.complete, "blocked": self.blocked, "ready_to_implement": self.ready}
        cited = [c for c in (candidates or []) if isinstance(c, dict) and c.get("id") and c.get("graph_ids")]
        for index, _cand in enumerate(cited):
            scores[f"grounded_{index}"] = self.grounded.get(f"grounded_{index}", 0.8)
        scores.update(self.extra_scores)
        return self._result(scores)

    def _result(self, scores: dict) -> DecisionResult:
        return DecisionResult(scores=scores, usage=DecisionUsage(input_tokens=self.usage), provider=self.provider, model=self.model, skipped=False, latency_ms=4.0)


class FakeLlm:
    def __init__(self, reply="llm reply", candidates=None):
        self.available = True
        self.reply = reply
        self.candidates = candidates if candidates is not None else [
            {"id": "custom.step", "label": "Write tests", "graph_ids": ["n1"]}
        ]
        self.called = 0
        self.messages = []
        self.last_usage = {"prompt_tokens": 40, "completion_tokens": 12}

    def chat_json(self, messages, model=None):
        self.called += 1
        self.messages = messages
        return {"reply": self.reply, "candidates": self.candidates}


@pytest.mark.asyncio
async def test_cycle_passes_pack_and_hits_to_decision_clients(tmp_path):
    _graph(tmp_path)
    client = FakeDecision(ready=0.95, blocked=0.05, complete=0.05)
    orch = Orchestrator(FakeGE(), relevance_client=client, judgment_client=client, llm=FakeLlm())
    await orch.run_suggest_cycle(str(tmp_path), "p", _task())
    assert client.filter_calls
    assert "n1:" in client.filter_calls[0]["pack"]
    assert client.filter_calls[0]["hits"][0]["id"] == "n1"
    assert client.judge_calls
    assert "n1:" in client.judge_calls[0]["pack"]


@pytest.mark.asyncio
async def test_auto_suggest_skips_llm_when_jev_is_sure(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    llm = FakeLlm()
    jev = FakeDecision(ready=0.92, blocked=0.05, complete=0.05)
    orch = Orchestrator(FakeGE(), relevance_client=jev, judgment_client=jev, llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(AgentTaskStatus.TODO))
    assert llm.called == 0
    assert result.escalated is False
    assert result.action_id == "loom.move_ready"
    assert result.confidence == 0.92
    assert result.reply == template_reply(result.action_label)
    assert result.jev_input_tokens == 22  # filter 11 + judge 11
    assert result.llm_prompt_tokens == 0


@pytest.mark.asyncio
async def test_auto_suggest_escalates_when_key_noul_in_mid_band(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    llm = FakeLlm(reply="because it is unclear")
    jev = FakeDecision(ready=0.5, blocked=0.2, complete=0.1)
    orch = Orchestrator(FakeGE(), relevance_client=jev, judgment_client=jev, llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(AgentTaskStatus.TODO))
    assert llm.called == 1
    assert result.escalated is True
    assert result.confidence < NOUL_YES
    assert result.reply == "because it is unclear"
    assert result.llm_prompt_tokens == 40
    assert result.llm_completion_tokens == 12


@pytest.mark.asyncio
async def test_auto_suggest_escalates_when_jev_skipped(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    llm = FakeLlm(reply="fallback prose")
    orch = Orchestrator(
        FakeGE(),
        jev=JevClient(api_key=""),  # unavailable → jev_skipped
        llm=llm,
    )
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task())
    assert result.jev_skipped is True
    assert result.escalated is True
    assert llm.called == 1
    assert result.reply == "fallback prose"


@pytest.mark.asyncio
async def test_chat_always_calls_llm_even_when_jev_is_sure(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    llm = FakeLlm(reply="here is a plan")
    jev = FakeDecision(ready=0.95, blocked=0.05, complete=0.05)
    orch = Orchestrator(FakeGE(), relevance_client=jev, judgment_client=jev, llm=llm)
    result = await orch.run_suggest_cycle(
        str(tmp_path), "p", _task(AgentTaskStatus.TODO),
        user_message="how should we start?",
    )
    assert llm.called == 1
    assert result.reply == "here is a plan"
    assert jev.judge_calls
    assert jev.judge_calls[0]["candidates"][0]["graph_ids"] == ["n1"]


def _graph(tmp_path):
    (tmp_path / "graphify-out").mkdir(exist_ok=True)
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")


@pytest.fixture(autouse=True)
def _clear_jev_filter_cache():
    clear_filter_cache()
    yield
    clear_filter_cache()


def test_build_context_pack_caps_chars():
    hits = [{"id": f"n{i}", "label": "X" * 80} for i in range(40)]
    pack = build_context_pack(hits, max_chars=500)
    assert len(pack) <= 500
    assert "n0:" in pack


def test_context_hash_stable_for_same_task_and_nodes():
    a = _task()
    b = _task()
    hits = [{"id": "n2"}, {"id": "n1"}]
    assert context_hash(a, hits) == context_hash(b, list(reversed(hits)))
    other = _task(title="Other")
    assert context_hash(a, hits) != context_hash(other, hits)


@pytest.mark.asyncio
async def test_auto_suggest_escalation_grounds_new_candidates(tmp_path):
    _graph(tmp_path)
    llm = FakeLlm(reply="unclear, maybe write tests")
    jev = FakeDecision(ready=0.5, blocked=0.2, complete=0.1, usage=11)
    orch = Orchestrator(FakeGE(), relevance_client=jev, judgment_client=jev, llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(AgentTaskStatus.TODO))
    assert llm.called == 1
    assert result.escalated is True
    assert len(jev.filter_calls) == 1
    assert len(jev.judge_calls) == 2
    assert jev.judge_calls[0]["candidates"] == []
    assert jev.judge_calls[1]["candidates"][0]["id"] == "custom.step"
    assert result.jev_input_tokens == 33
    assert result.filter_input_tokens == 11
    assert result.judgment_input_tokens == 22


@pytest.mark.asyncio
async def test_filter_cache_skips_second_jev_filter(tmp_path):
    _graph(tmp_path)
    jev = FakeDecision(ready=0.92, blocked=0.05, complete=0.05, usage=11)
    llm = FakeLlm()
    orch = Orchestrator(FakeGE(), relevance_client=jev, judgment_client=jev, llm=llm)
    task = _task(AgentTaskStatus.TODO)
    first = await orch.run_suggest_cycle(str(tmp_path), "p", task)
    assert first.filter_cache_hit is False
    assert first.jev_input_tokens == 22  # filter + judge
    assert first.filter_input_tokens == 11
    assert first.judgment_input_tokens == 11
    second = await orch.run_suggest_cycle(str(tmp_path), "p", task)
    assert second.filter_cache_hit is True
    # only the judge is billed on the second cycle; cache does not invent filter tokens
    assert second.jev_input_tokens == 11
    assert second.filter_input_tokens is None
    assert second.judgment_input_tokens == 11
    assert len(jev.filter_calls) == 1
    assert len(jev.judge_calls) == 2
    assert llm.called == 0


@pytest.mark.asyncio
async def test_filter_none_uses_top_hybrid_hits_and_records_skip(tmp_path):
    _graph(tmp_path)
    hits = [{"id": f"n{i}", "label": f"Node{i}"} for i in range(8)]
    judgment = FakeDecision(ready=0.95, blocked=0.05, complete=0.05)
    orch = Orchestrator(FakeGE(hits), relevance_client=NullDecisionClient(), judgment_client=judgment, llm=FakeLlm())
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task())
    pack = judgment.judge_calls[0]["pack"]
    for index in range(5):
        assert f"n{index}:" in pack
    assert "n5:" not in pack
    assert result.filter_skipped is True
    assert result.filter_skip_reason == "none"
    assert result.filter_provider == "none"
    assert result.filter_input_tokens is None
    assert result.escalated is True


@pytest.mark.asyncio
async def test_missing_relevance_score_is_mid_band_and_unknown_keys_ignored(tmp_path):
    _graph(tmp_path)
    hits = [{"id": "n1", "label": "Kept"}, {"id": "n2", "label": "Unscored"}]
    client = FakeDecision(rel={"rel_0": 0.95}, ready=0.95, blocked=0.05, complete=0.05, extra_scores={"mystery": 0.99, "rel_9": 0.99})
    orch = Orchestrator(FakeGE(hits), relevance_client=client, judgment_client=client, llm=FakeLlm())
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task())
    pack = client.judge_calls[0]["pack"]
    assert "n1:" in pack
    assert "n2:" in pack
    assert result.escalated is False
    dropped = FakeDecision(rel={"rel_0": 0.95, "rel_1": 0.05}, ready=0.95, blocked=0.05, complete=0.05, extra_scores={"mystery": 1.0})
    orch2 = Orchestrator(FakeGE(hits), relevance_client=dropped, judgment_client=dropped, llm=FakeLlm())
    await orch2.run_suggest_cycle(str(tmp_path), "p", _task(title="Other task"))
    assert "n2:" not in dropped.judge_calls[0]["pack"]


@pytest.mark.asyncio
async def test_escalate_threshold_calls_llm_when_score_is_below_it(tmp_path):
    _graph(tmp_path)
    client = FakeDecision(ready=0.75, blocked=0.05, complete=0.05)
    settings = {"filter_provider": "typesafe", "judgment_provider": "typesafe", "threshold_overrides": {"typesafe": {"drop": 0.2, "mid": 0.4, "keep": 0.6, "escalate": 0.9}}}
    llm = FakeLlm(reply="below escalate")
    orch = Orchestrator(FakeGE(), relevance_client=client, judgment_client=client, llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(), settings=settings)
    assert result.confidence == 0.75
    assert result.escalated is True
    assert llm.called == 1
    assert '"escalate": 0.9' in result.effective_thresholds_json


@pytest.mark.asyncio
async def test_null_judgment_auto_suggest_escalates_and_grounds(tmp_path):
    _graph(tmp_path)

    class SpyNull(NullDecisionClient):
        def __init__(self):
            self.judge_calls = []

        def judge(self, *, pack, task, catalog, candidates, **kwargs):
            self.judge_calls.append(list(candidates))
            return super().judge(pack=pack, task=task, catalog=catalog, candidates=candidates)

    judgment = SpyNull()
    relevance = FakeDecision(ready=0.95, blocked=0.05, complete=0.05)
    llm = FakeLlm()
    orch = Orchestrator(FakeGE(), relevance_client=relevance, judgment_client=judgment, llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task())
    assert result.judgment_skipped is True
    assert result.judgment_skip_reason == "none"
    assert result.judgment_provider == "none"
    assert result.escalated is True
    assert llm.called == 1
    assert len(judgment.judge_calls) == 2
    assert judgment.judge_calls[1]


@pytest.mark.asyncio
async def test_filter_cache_key_includes_provider_and_model(tmp_path):
    _graph(tmp_path)
    sure = dict(ready=0.95, blocked=0.05, complete=0.05)
    first_client = FakeDecision(provider="typesafe", model="model-a", **sure)
    second_client = FakeDecision(provider="ollama", model="model-b", **sure)
    task = _task()
    orch_a = Orchestrator(FakeGE(), relevance_client=first_client, judgment_client=first_client, llm=FakeLlm())
    orch_b = Orchestrator(FakeGE(), relevance_client=second_client, judgment_client=second_client, llm=FakeLlm())
    first = await orch_a.run_suggest_cycle(str(tmp_path), "p", task)
    second = await orch_b.run_suggest_cycle(str(tmp_path), "p", task)
    assert first.filter_cache_hit is False
    assert second.filter_cache_hit is False
    assert len(second_client.filter_calls) == 1
    third = await orch_a.run_suggest_cycle(str(tmp_path), "p", task)
    assert third.filter_cache_hit is True
    assert len(first_client.filter_calls) == 1
    fourth = await orch_a.run_suggest_cycle(str(tmp_path), "p", _task(title="Different title"))
    assert fourth.filter_cache_hit is False
    assert len(first_client.filter_calls) == 2


def test_filter_cache_key_includes_thresholds():
    from daemon.orchestrator import filter_cache_key

    a = filter_cache_key("typesafe", "m", "ctx", {"keep": 0.7, "drop": 0.3})
    b = filter_cache_key("typesafe", "m", "ctx", {"keep": 0.9, "drop": 0.1})
    c = filter_cache_key("typesafe", "m", "ctx", {"drop": 0.3, "keep": 0.7})
    assert a != b
    assert a == c


@pytest.mark.asyncio
async def test_filter_cache_misses_when_thresholds_change(tmp_path):
    from daemon.orchestrator import clear_filter_cache

    clear_filter_cache()
    _graph(tmp_path)
    sure = dict(ready=0.95, blocked=0.05, complete=0.05)
    client = FakeDecision(provider="typesafe", model="model-a", **sure)
    task = _task()
    orch = Orchestrator(FakeGE(), relevance_client=client, judgment_client=client, llm=FakeLlm())
    settings_a = {
        "filter_provider": "typesafe",
        "judgment_provider": "typesafe",
        "threshold_overrides": {"typesafe": {"keep": 0.6, "drop": 0.2}},
    }
    settings_b = {
        "filter_provider": "typesafe",
        "judgment_provider": "typesafe",
        "threshold_overrides": {"typesafe": {"keep": 0.9, "drop": 0.1}},
    }
    first = await orch.run_suggest_cycle(str(tmp_path), "p", task, settings=settings_a, raw_keys={"typesafe": "k"})
    assert first.filter_cache_hit is False
    assert len(client.filter_calls) == 1
    second = await orch.run_suggest_cycle(str(tmp_path), "p", task, settings=settings_b, raw_keys={"typesafe": "k"})
    assert second.filter_cache_hit is False
    assert len(client.filter_calls) == 2
    third = await orch.run_suggest_cycle(str(tmp_path), "p", task, settings=settings_b, raw_keys={"typesafe": "k"})
    assert third.filter_cache_hit is True
    assert len(client.filter_calls) == 2


@pytest.mark.asyncio
async def test_invalid_ollama_config_skips_without_crashing(tmp_path):
    _graph(tmp_path)
    llm = FakeLlm(reply="config failed")
    settings = {"filter_provider": "ollama", "judgment_provider": "ollama", "providers": [{"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434", "model_ids": []}]}
    orch = Orchestrator(FakeGE(), llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(), settings=settings, raw_keys={})
    assert result.filter_skipped is True
    assert result.filter_skip_reason == "error"
    assert result.judgment_skipped is True
    assert result.judgment_skip_reason == "error"
    assert result.escalated is True
    assert llm.called == 1
    assert result.reply == "config failed"


@pytest.mark.asyncio
async def test_runtime_persists_decision_telemetry(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from daemon.agent_runtime import AgentRuntime
    from daemon.registry import AgentRegistry

    reg = AgentRegistry(str(tmp_path / "state.db"))
    await reg.initialize()
    try:
        tid = await reg.create_agent_task(AgentTaskCreatePayload(project="p", title="T", instruction="do thing"), status=AgentTaskStatus.TODO)
        runtime = AgentRuntime(reg, FakeGE())
        sug = await runtime.suggest("p", str(tmp_path), tid)
        assert sug.filter_provider == "none"
        assert sug.judgment_provider == "none"
        assert sug.filter_skipped is True
        assert sug.filter_skip_reason == "none"
        assert sug.judgment_skipped is True
        assert sug.judgment_skip_reason == "none"
        assert sug.filter_input_tokens is None
        assert sug.judgment_input_tokens is None
        assert sug.jev_skipped is True
        assert sug.escalated is True
        assert sug.effective_thresholds_json
        import json
        payload = json.loads(sug.effective_thresholds_json)
        assert payload["filter"]["keep"] == 0.7
        assert "escalate" in payload["judgment"]
    finally:
        await reg.close()


def test_all_below_drop_fallback_keeps_highest_scores():
    hits = [{"id": name, "label": name} for name in ("a", "b", "c", "d", "e", "f")]
    scores = {"rel_0": 0.05, "rel_1": 0.25, "rel_2": 0.01, "rel_3": 0.22, "rel_4": 0.18, "rel_5": 0.02}
    selected, mid_keys = select_relevant_hits(hits, scores, {"drop": 0.3, "mid": 0.5, "keep": 0.7, "escalate": 0.7})
    assert [hit["id"] for hit in selected] == ["b", "d", "e", "a"]
    assert mid_keys == []


@pytest.mark.asyncio
async def test_grounding_failure_keeps_successful_judgment(tmp_path, caplog):
    _graph(tmp_path)

    class GroundFails(FakeDecision):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._judgments = 0

        def judge(self, *, pack, task, catalog, candidates, **kwargs):
            self._judgments += 1
            if self._judgments > 1:
                self.judge_calls.append({"pack": pack, "candidates": candidates})
                return DecisionResult(provider=self.provider, model="ground-fail", skipped=True, skip_reason="timeout", latency_ms=99.0, usage=DecisionUsage(input_tokens=50))
            result = super().judge(pack=pack, task=task, catalog=catalog, candidates=candidates)
            result.latency_ms = 12.0
            return result

    client = GroundFails(ready=0.5, blocked=0.2, complete=0.1)
    llm = FakeLlm(reply="still the first judgment")
    orch = Orchestrator(FakeGE(), relevance_client=client, judgment_client=client, llm=llm)
    with caplog.at_level("WARNING"):
        result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(AgentTaskStatus.TODO))
    assert llm.called == 1
    assert len(client.judge_calls) == 2
    assert result.escalated is True
    assert result.action_id == "loom.move_ready"
    assert result.confidence == 0.5
    assert result.judgment_skipped is False
    assert result.judgment_skip_reason is None
    assert result.judgment_latency_ms == 12.0
    assert result.judgment_input_tokens == 61  # first judge 11 + failed grounding 50
    assert result.judgment_model == "jev-latest"
    assert "keeping prior decision" in caplog.text
