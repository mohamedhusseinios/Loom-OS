"""Orchestrator catalog merge, judgments, mid-band filter, and auto-suggest escalation."""
import pytest

from daemon.models import AgentTaskRecord, AgentTaskStatus
from daemon.orchestrator import (
    Orchestrator, merge_catalog, loom_catalog_for_status, SuggestResult,
    Judgments, map_judgments_to_action, partition_relevance, NOUL_YES,
    template_reply, build_context_pack, context_hash, clear_filter_cache,
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


class FakeJev:
    def __init__(self, rel=None, complete=0.1, blocked=0.1, ready=0.9, grounded=None, usage=11):
        self.available = True
        self.rel = rel if rel is not None else {"rel_0": 0.9, "rel_1": 0.2}
        self.complete = complete
        self.blocked = blocked
        self.ready = ready
        self.grounded = grounded or {}
        self.usage = usage
        self.calls: list[dict] = []

    def ask(self, state, questions, model="jev-latest"):
        self.calls.append(questions)
        answers = {}
        if any(k.startswith("rel_") for k in questions):
            for key in questions:
                answers[key] = {"type": "noul", "noul": self.rel.get(key, 0.1)}
        else:
            answers["complete"] = {"type": "noul", "noul": self.complete}
            answers["blocked"] = {"type": "noul", "noul": self.blocked}
            answers["ready_to_implement"] = {"type": "noul", "noul": self.ready}
            for key in questions:
                if key.startswith("grounded_"):
                    answers[key] = {"type": "noul", "noul": self.grounded.get(key, 0.8)}
        return {
            "answers": answers,
            "usage": {"input_tokens": self.usage, "output_tokens": 2},
            "model": "jev-latest",
        }


class FakeLlm:
    def __init__(self, reply="llm reply", candidates=None):
        self.available = True
        self.reply = reply
        self.candidates = candidates if candidates is not None else [
            {"id": "custom.step", "label": "Write tests", "graph_ids": ["n1"]}
        ]
        self.called = 0
        self.last_usage = {"prompt_tokens": 40, "completion_tokens": 12}

    def chat_json(self, messages, model=None):
        self.called += 1
        return {"reply": self.reply, "candidates": self.candidates}


def test_jev_filter_and_judge_send_criteria_not_options(tmp_path):
    jev = FakeJev()
    orch = Orchestrator(FakeGE(), jev=jev, llm=FakeLlm())
    # Run the sync helpers directly to inspect payloads.
    task = _task()
    orch._jev_filter(FakeGE().hits, task)
    filter_q = jev.calls[0]
    assert "rel_0" in filter_q
    assert filter_q["rel_0"]["type"] == "noul"
    assert "criteria" in filter_q["rel_0"]
    assert "true" in filter_q["rel_0"]["criteria"]
    assert "options" not in filter_q["rel_0"]

    orch._jev_judge("pack", task, _catalog("todo"), [
        {"id": "custom.step", "label": "Write tests", "graph_ids": ["n1"]}
    ])
    judge_q = jev.calls[1]
    for key in ("complete", "blocked", "ready_to_implement", "grounded_0"):
        assert key in judge_q
        assert judge_q[key]["type"] == "noul"
        assert "criteria" in judge_q[key]
        assert "options" not in judge_q[key]
    assert "next_step" not in judge_q


@pytest.mark.asyncio
async def test_auto_suggest_skips_llm_when_jev_is_sure(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    llm = FakeLlm()
    jev = FakeJev(ready=0.92, blocked=0.05, complete=0.05)
    orch = Orchestrator(FakeGE(), jev=jev, llm=llm)
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
    jev = FakeJev(ready=0.5, blocked=0.2, complete=0.1)
    orch = Orchestrator(FakeGE(), jev=jev, llm=llm)
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
    jev = FakeJev(ready=0.95, blocked=0.05, complete=0.05)
    orch = Orchestrator(FakeGE(), jev=jev, llm=llm)
    result = await orch.run_suggest_cycle(
        str(tmp_path), "p", _task(AgentTaskStatus.TODO),
        user_message="how should we start?",
    )
    assert llm.called == 1
    assert result.reply == "here is a plan"
    # Grounding question is asked because candidates exist before judge.
    judge_calls = [c for c in jev.calls if "complete" in c]
    assert judge_calls and "grounded_0" in judge_calls[0]


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
    jev = FakeJev(ready=0.5, blocked=0.2, complete=0.1, usage=11)
    orch = Orchestrator(FakeGE(), jev=jev, llm=llm)
    result = await orch.run_suggest_cycle(str(tmp_path), "p", _task(AgentTaskStatus.TODO))
    assert llm.called == 1
    assert result.escalated is True
    # filter + initial judge + grounding pass
    kinds = []
    for call in jev.calls:
        if any(k.startswith("rel_") for k in call):
            kinds.append("filter")
        elif "complete" in call:
            kinds.append("judge")
        elif any(k.startswith("grounded_") for k in call) and "complete" not in call:
            kinds.append("ground")
        else:
            kinds.append("other")
    assert kinds == ["filter", "judge", "ground"]
    assert "grounded_0" in jev.calls[-1]
    assert "options" not in jev.calls[-1]["grounded_0"]
    assert "criteria" in jev.calls[-1]["grounded_0"]
    assert result.jev_input_tokens == 33


@pytest.mark.asyncio
async def test_filter_cache_skips_second_jev_filter(tmp_path):
    _graph(tmp_path)
    jev = FakeJev(ready=0.92, blocked=0.05, complete=0.05, usage=11)
    llm = FakeLlm()
    orch = Orchestrator(FakeGE(), jev=jev, llm=llm)
    task = _task(AgentTaskStatus.TODO)
    first = await orch.run_suggest_cycle(str(tmp_path), "p", task)
    assert first.filter_cache_hit is False
    assert first.jev_input_tokens == 22  # filter + judge
    second = await orch.run_suggest_cycle(str(tmp_path), "p", task)
    assert second.filter_cache_hit is True
    # only the judge is billed on the second cycle
    assert second.jev_input_tokens == 11
    filters = [c for c in jev.calls if any(k.startswith("rel_") for k in c)]
    judges = [c for c in jev.calls if "complete" in c]
    assert len(filters) == 1
    assert len(judges) == 2
    assert llm.called == 0
