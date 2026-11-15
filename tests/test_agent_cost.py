"""Cost summary, report script, hash-skip, and API endpoint tests."""
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import daemon.api as api_module
from daemon.agent_cost import format_report, jev_cost_usd, summarize_suggestions
from daemon.agent_runtime import SUGGEST_COOLDOWN_SEC, AgentRuntime, _suggest_cooldown
from daemon.graph_engine import GraphEngine
from daemon.models import (
    AgentInfo, AgentTaskCreatePayload, AgentTaskStatus, SuggestionStatus,
)
from daemon.orchestrator import SuggestResult, clear_filter_cache, context_hash
from daemon.registry import AgentRegistry
from scripts.agent_cost_report import FIXED_BENCHMARK_TASKS, main as report_main


def test_summarize_and_jev_price():
    rows = [
        {"jev_input_tokens": 1_000_000, "llm_prompt_tokens": 10, "llm_completion_tokens": 5,
         "escalated": 1, "status": "accepted"},
        {"jev_input_tokens": 0, "llm_prompt_tokens": 20, "llm_completion_tokens": 5,
         "escalated": 0, "status": "dismissed"},
        {"jev_input_tokens": 0, "llm_prompt_tokens": 0, "llm_completion_tokens": 0,
         "escalated": 0, "status": "pending"},
    ]
    s = summarize_suggestions(rows)
    assert s["suggestion_count"] == 3
    assert s["jev_input_tokens"] == 1_000_000
    assert s["jev_cost_usd"] == jev_cost_usd(1_000_000)
    assert s["jev_cost_usd"] == 0.042
    assert s["llm_total_tokens"] == 40
    assert s["escalation_rate"] == pytest.approx(1 / 3)
    assert s["accept_rate_resolved"] == pytest.approx(0.5)
    assert s["dismiss_rate_resolved"] == pytest.approx(0.5)
    text = format_report(s)
    assert "$0.042" in text or "$0.042000" in text
    assert "n/a" in text
    priced = format_report(s, deepseek_input_price=1.0, deepseek_output_price=2.0)
    assert "llm_cost_usd" in priced
    assert "llm_cost_usd:          n/a" not in priced
    assert "gliclass_cost_usd:     n/a" in priced


def test_summarize_reports_providers_skips_and_gliclass_cost():
    rows = [
        {
            "filter_provider": "gliclass", "filter_model": "knowledgator",
            "filter_input_tokens": None, "filter_skipped": 0, "filter_skip_reason": None,
            "filter_latency_ms": 20,
            "judgment_provider": "typesafe", "judgment_model": "jev-latest",
            "judgment_input_tokens": 1_000_000, "judgment_skipped": 0, "judgment_skip_reason": None,
            "judgment_latency_ms": 10,
            "llm_prompt_tokens": 0, "llm_completion_tokens": 0,
            "escalated": 0, "status": "accepted",
        },
        {
            "filter_provider": "typesafe", "filter_model": "jev-latest",
            "filter_input_tokens": 0, "filter_skipped": 1, "filter_skip_reason": "timeout",
            "filter_latency_ms": 8,
            "judgment_provider": "ollama", "judgment_model": "qwen",
            "judgment_input_tokens": 0, "judgment_skipped": 1, "judgment_skip_reason": "error",
            "judgment_latency_ms": 4,
            "llm_prompt_tokens": 0, "llm_completion_tokens": 0,
            "escalated": 1, "status": "dismissed",
        },
        {
            "filter_input_tokens": None, "judgment_input_tokens": None,
            "legacy_decision_input_tokens": 42, "jev_input_tokens": 42,
            "llm_prompt_tokens": 0, "llm_completion_tokens": 0,
            "escalated": 0, "status": "pending",
        },
    ]
    summary = summarize_suggestions(rows)
    assert summary["filter_input_tokens"] == 0
    assert summary["judgment_input_tokens"] == 1_000_000
    assert summary["legacy_input_tokens"] == 42
    assert summary["jev_input_tokens"] == 1_000_000 + 42
    assert summary["jev_cost_usd"] == round(jev_cost_usd(1_000_000 + 42), 8)
    assert summary["gliclass_cost_usd"] is None
    assert summary["gliclass_calls"] == 1
    assert summary["filter_skips_by_reason"] == {"timeout": 1}
    assert summary["judgment_skips_by_reason"] == {"error": 1}
    assert summary["filter_skip_rate"] == pytest.approx(1 / 3)
    assert summary["filter_latency_ms_avg"] == pytest.approx(14)
    assert summary["judgment_latency_ms_avg"] == pytest.approx(7)
    text = format_report(summary)
    assert "gliclass_cost_usd:     n/a" in text
    assert "timeout=1" in text
    assert "error=1" in text
    assert "gliclass/knowledgator" in text
    gliclass = next(item for item in summary["providers"] if item["provider"] == "gliclass")
    assert gliclass["cost_usd"] is None
    assert gliclass["latency_ms_avg"] == pytest.approx(20)


def test_ollama_tokens_not_priced_as_jev():
    summary = summarize_suggestions([{
        "filter_provider": "ollama", "filter_model": "nimble",
        "filter_input_tokens": 500_000, "filter_skipped": 0, "filter_skip_reason": None,
        "judgment_provider": "ollama", "judgment_model": "nimble",
        "judgment_input_tokens": 500_000, "judgment_skipped": 0, "judgment_skip_reason": None,
        "llm_prompt_tokens": 0, "llm_completion_tokens": 0,
        "escalated": 0, "status": "accepted",
    }])
    assert summary["filter_input_tokens"] == 500_000
    assert summary["judgment_input_tokens"] == 500_000
    assert summary["jev_input_tokens"] == 0
    assert summary["jev_cost_usd"] == 0.0
    ollama_rows = [item for item in summary["providers"] if item["provider"] == "ollama"]
    assert ollama_rows
    assert all(item["cost_usd"] is None for item in ollama_rows)
    text = format_report(summary)
    assert "jev_input_tokens:      0" in text
    assert "cost=n/a" in text


def test_none_judgment_latency_stays_on_filter_sample():
    from scripts.agent_cost_report import format_comparison

    summary = summarize_suggestions([{
        "filter_provider": "gliclass", "filter_model": "gli",
        "filter_input_tokens": None, "filter_skipped": 0, "filter_skip_reason": None,
        "filter_latency_ms": 40.0,
        "judgment_provider": "none", "judgment_model": "",
        "judgment_input_tokens": None, "judgment_skipped": 1, "judgment_skip_reason": "none",
        "judgment_latency_ms": 0.02,
        "llm_prompt_tokens": 0, "llm_completion_tokens": 0,
        "escalated": 1, "status": "pending",
    }])
    assert summary["filter_latency_ms_avg"] == pytest.approx(40.0)
    assert summary["judgment_latency_ms_avg"] is None
    none_row = next(item for item in summary["providers"] if item["provider"] == "none")
    assert none_row["latency_ms_avg"] is None
    table = format_comparison([("gliclass/gli judgment none/-", summary)])
    assert table.splitlines()[1].split()[-1] == "40.0"


def test_report_script_reads_db(tmp_path, capsys):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE task_suggestions (
            id TEXT, project TEXT, task_id TEXT, action_id TEXT, action_label TEXT,
            confidence REAL, prose TEXT, catalog_json TEXT, status TEXT,
            jev_skipped INTEGER, jev_input_tokens INTEGER, llm_prompt_tokens INTEGER,
            llm_completion_tokens INTEGER, escalated INTEGER, created_at TEXT, updated_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO task_suggestions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", "p", "t1", "loom.move_ready", "Ready", 0.9, "go", "[]", "accepted",
         0, 100, 40, 10, 1, "now", "now"),
    )
    conn.commit()
    conn.close()
    assert report_main(["--db", str(db), "--project", "p"]) == 0
    out = capsys.readouterr().out
    assert "suggestions:           1" in out
    assert "jev_input_tokens:      100" in out


def test_benchmark_exits_cleanly_without_keys(tmp_path, capsys):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TYPESAFE_API_KEY", "DEEPSEEK_API_KEY", "LOOM_AGENT_API_KEY", "LOOM_DB_PATH")}
    empty_db = tmp_path / "empty.db"
    with patch.dict(os.environ, env, clear=True):
        rc = report_main(["--benchmark", "--db", str(empty_db)])
    err = capsys.readouterr().err
    assert rc == 0
    assert "Skipping benchmark" in err
    assert "API_KEY" in err


def test_benchmark_keys_present_from_settings(tmp_path, monkeypatch):
    import json
    from scripts.agent_cost_report import _keys_present, resolve_benchmark_credentials

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE agent_settings ("
        " id INTEGER PRIMARY KEY, default_model TEXT,"
        " providers_json TEXT, api_keys_json TEXT)"
    )
    conn.execute(
        "INSERT INTO agent_settings VALUES (1, ?, ?, ?)",
        (
            "deepseek-chat",
            json.dumps([
                {"id": "deepseek", "name": "DeepSeek",
                 "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]},
                {"id": "typesafe", "name": "TypeSafe (Jev)",
                 "base_url": "http://localhost:11434", "model_ids": ["jev-latest"]},
            ]),
            json.dumps({"deepseek": "sk-dash-ds", "typesafe": "ts-dash-jev"}),
        ),
    )
    conn.commit()
    conn.close()
    assert _keys_present(str(db)) is True
    ts_key, ts_base, ds_key, ds_base, model = resolve_benchmark_credentials(str(db))
    assert ts_key == "ts-dash-jev"
    assert ts_base == "http://localhost:11434"
    assert ds_key == "sk-dash-ds"
    assert "deepseek" in ds_base
    assert model == "deepseek-chat"


def test_benchmark_settings_key_wins_over_env(tmp_path, monkeypatch):
    import json
    from scripts.agent_cost_report import resolve_benchmark_credentials

    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE agent_settings ("
        " id INTEGER PRIMARY KEY, default_model TEXT,"
        " providers_json TEXT, api_keys_json TEXT)"
    )
    conn.execute(
        "INSERT INTO agent_settings VALUES (1, ?, ?, ?)",
        (
            "deepseek-chat",
            json.dumps([]),
            json.dumps({"deepseek": "sk-from-settings", "typesafe": "ts-from-settings"}),
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-from-env")
    ts_key, _, ds_key, _, _ = resolve_benchmark_credentials(str(db))
    assert ts_key == "ts-from-settings"
    assert ds_key == "sk-from-settings"


@pytest.mark.asyncio
async def test_cost_summary_api(tmp_path):
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()
    await registry.upsert_project("noor", str(tmp_path / "noor"))
    api_module.registry = registry
    api_module.graph_engine = GraphEngine()
    api_module.router = None
    api_module.watcher = None
    api_module.supervisor = None
    api_module.agent_runtime = None
    missing = TestClient(api_module.app).get("/api/projects/missing/agent/cost-summary")
    assert missing.status_code == 404
    await registry.create_task_suggestion(
        "noor", "t1", "loom.move_ready", "Ready", 0.8, "go", [],
        jev_input_tokens=22, llm_prompt_tokens=40, llm_completion_tokens=12, escalated=True,
        filter_provider="typesafe", filter_model="jev-latest",
        judgment_provider="typesafe", judgment_model="jev-latest",
        filter_input_tokens=10, judgment_input_tokens=12,
        filter_skipped=False, judgment_skipped=True, judgment_skip_reason="timeout",
        filter_latency_ms=3, judgment_latency_ms=9,
    )
    await registry.set_suggestion_status(
        (await registry.get_pending_suggestion("t1")).id, SuggestionStatus.ACCEPTED,
    )
    with TestClient(api_module.app) as c:
        res = c.get("/api/projects/noor/agent/cost-summary")
    assert res.status_code == 200
    body = res.json()
    assert body["suggestion_count"] == 1
    assert body["jev_input_tokens"] == 22
    assert body["filter_input_tokens"] == 10
    assert body["judgment_input_tokens"] == 12
    assert body["judgment_skips_by_reason"]["timeout"] == 1
    assert body["llm_total_tokens"] == 52
    assert body["accepted"] == 1
    assert body["escalation_rate"] == 1.0
    assert body["gliclass_cost_usd"] is None
    await registry.close()


@pytest.mark.asyncio
async def test_auto_suggest_skips_unchanged_hash_even_after_cooldown(tmp_path):
    clear_filter_cache()
    _suggest_cooldown.clear()
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()
    await registry.upsert_project("p", str(tmp_path))
    tid = await registry.create_agent_task(AgentTaskCreatePayload(
        project="p", title="T", instruction="do thing",
    ))
    task = await registry.get_agent_task(tid)
    hits = [{"id": "n1", "label": "Auth"}]

    class FakeGE:
        async def hybrid_query(self, *a, **k):
            return list(hits)

    runtime = AgentRuntime(registry, FakeGE())
    ctx = context_hash(task, hits)
    existing = await registry.create_task_suggestion(
        "p", tid, "loom.move_ready", "Move task to Ready", 0.9, "keep", [],
        context_hash=ctx,
    )
    _suggest_cooldown[tid] = time.monotonic() - SUGGEST_COOLDOWN_SEC - 1
    with patch("daemon.agent_runtime.Orchestrator") as orch_cls:
        result = await runtime.suggest("p", str(tmp_path), tid, force=False)
    orch_cls.assert_not_called()
    assert result.id == existing.id
    await registry.close()


@pytest.mark.asyncio
async def test_manual_suggest_still_runs_when_hash_unchanged(tmp_path):
    clear_filter_cache()
    _suggest_cooldown.clear()
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()
    await registry.upsert_project("p", str(tmp_path))
    tid = await registry.create_agent_task(AgentTaskCreatePayload(
        project="p", title="T", instruction="do thing",
    ))
    task = await registry.get_agent_task(tid)
    hits = [{"id": "n1", "label": "Auth"}]

    class FakeGE:
        async def hybrid_query(self, *a, **k):
            return list(hits)

    runtime = AgentRuntime(registry, FakeGE())
    await registry.create_task_suggestion(
        "p", tid, "loom.move_ready", "Move task to Ready", 0.9, "old", [],
        context_hash=context_hash(task, hits),
    )
    fake_result = SuggestResult(
        action_id="loom.move_blocked",
        action_label="Move task to Blocked",
        confidence=0.8,
        prose="new",
        context_hash=context_hash(task, hits),
    )

    class FakeOrch:
        def __init__(self, *a, **k):
            pass

        async def run_suggest_cycle(self, *a, **k):
            return fake_result

    with patch("daemon.agent_runtime.Orchestrator", FakeOrch),             patch.object(runtime, "_llm_from_settings", return_value=(MagicMock(), "deepseek-chat")):
        result = await runtime.suggest("p", str(tmp_path), tid, force=True)
    assert result.action_id == "loom.move_blocked"
    assert result.prose == "new"
    await registry.close()


def test_benchmark_fixture_is_non_empty():
    assert len(FIXED_BENCHMARK_TASKS) >= 3
    assert all("hits" in t and "title" in t for t in FIXED_BENCHMARK_TASKS)


def _silence_provider_env(monkeypatch):
    for name in (
        "TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "DEEPSEEK_API_KEY", "LOOM_AGENT_API_KEY",
        "OLLAMA_MODEL", "OLLAMA_BASE_URL", "OLLAMA_API_KEY", "GLICLASS_BASE_URL", "LOOM_DB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def _settings_db(path, providers, keys, default_model="deepseek-chat", filter_provider="gliclass", judgment_provider="none"):
    import json
    if Path(path).exists():
        Path(path).unlink()
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE agent_settings ("
        " id INTEGER PRIMARY KEY, default_model TEXT,"
        " providers_json TEXT, api_keys_json TEXT,"
        " filter_provider TEXT, judgment_provider TEXT)"
    )
    conn.execute(
        "INSERT INTO agent_settings (id, default_model, providers_json, api_keys_json, filter_provider, judgment_provider)"
        " VALUES (1, ?, ?, ?, ?, ?)",
        (default_model, json.dumps(providers), json.dumps(keys), filter_provider, judgment_provider),
    )
    conn.commit()
    conn.close()


def test_configured_targets_need_key_model_and_url(tmp_path, monkeypatch):
    from scripts.agent_cost_report import configured_decision_targets

    _silence_provider_env(monkeypatch)
    db = tmp_path / "state.db"
    _settings_db(
        db,
        providers=[
            {"id": "typesafe", "name": "TypeSafe", "base_url": "https://api.typesafe.ai", "model_ids": ["jev-latest"]},
            {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434", "model_ids": []},
            {"id": "gliclass", "name": "GLiClass", "base_url": "", "model_ids": []},
        ],
        keys={"typesafe": "ts-key", "deepseek": "sk-ds"},
    )
    only_typesafe = configured_decision_targets(str(db))
    assert [item["filter_provider"] for item in only_typesafe] == ["typesafe"]

    _settings_db(
        db,
        providers=[
            {"id": "typesafe", "name": "TypeSafe", "base_url": "", "model_ids": ["jev-latest"]},
            {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434", "model_ids": ["qwen"]},
            {"id": "gliclass", "name": "GLiClass", "base_url": "http://127.0.0.1:8080", "model_ids": ["gli"]},
        ],
        keys={"typesafe": "ts-key", "deepseek": "sk-ds"},
    )
    names = [item["filter_provider"] for item in configured_decision_targets(str(db))]
    assert names == ["typesafe", "ollama", "gliclass"]
    gliclass = configured_decision_targets(str(db))[-1]
    assert gliclass["judgment_provider"] == "none"
    assert gliclass["settings"]["judgment_provider"] == "none"


def test_benchmark_compares_configured_providers(tmp_path, monkeypatch, capsys):
    from scripts import agent_cost_report as report_mod

    _silence_provider_env(monkeypatch)
    db = tmp_path / "state.db"
    _settings_db(
        db,
        providers=[
            {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]},
            {"id": "typesafe", "name": "TypeSafe", "base_url": "https://api.typesafe.ai", "model_ids": ["jev-latest"]},
            {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434", "model_ids": ["qwen"]},
            {"id": "gliclass", "name": "GLiClass", "base_url": "http://127.0.0.1:8080", "model_ids": ["gli"]},
        ],
        keys={"deepseek": "sk-ds", "typesafe": "ts-key"},
        filter_provider="typesafe",
        judgment_provider="typesafe",
    )
    seen = []

    async def fake_cycle(variant, db_path=None):
        seen.append((variant["filter_provider"], bool(variant.get("always_llm")), variant["judgment_provider"]))
        provider = variant["filter_provider"]
        return [{
            "filter_provider": provider,
            "filter_model": variant.get("filter_model") or "",
            "judgment_provider": variant["judgment_provider"],
            "judgment_model": variant.get("judgment_model") or "",
            "filter_input_tokens": None if provider == "gliclass" else 10,
            "judgment_input_tokens": None if variant["judgment_provider"] == "none" else 5,
            "filter_skipped": provider == "gliclass",
            "judgment_skipped": variant["judgment_provider"] == "none",
            "filter_skip_reason": "none" if provider == "gliclass" else None,
            "judgment_skip_reason": "none" if variant["judgment_provider"] == "none" else None,
            "filter_latency_ms": 4.0,
            "judgment_latency_ms": 6.0,
            "llm_prompt_tokens": 3,
            "llm_completion_tokens": 1,
            "escalated": provider == "gliclass",
            "status": "pending",
        }]

    monkeypatch.setattr(report_mod, "_run_benchmark_cycle", fake_cycle)
    assert report_mod.main(["--benchmark", "--db", str(db)]) == 0
    assert ("typesafe", True, "typesafe") in seen
    assert {provider for provider, always, _judgment in seen if not always} == {"typesafe", "ollama", "gliclass"}
    out = capsys.readouterr().out
    assert "== comparison ==" in out
    assert "gliclass" in out
    assert "n/a" in out
    assert "accept/dismiss stay 0" in out


def test_smoke_script_is_manual_and_calls_each_configured_provider(tmp_path, monkeypatch, capsys):
    from scripts import decision_provider_smoke as smoke

    _silence_provider_env(monkeypatch)
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert smoke.main(["--db", str(empty)]) == 0
    skipped = capsys.readouterr().out
    assert "Manual only" in skipped
    assert "not CI" in skipped
    assert "No configured decision provider" in skipped

    db = tmp_path / "state.db"
    _settings_db(
        db,
        providers=[
            {"id": "typesafe", "name": "TypeSafe", "base_url": "https://api.typesafe.ai", "model_ids": ["jev-latest"]},
            {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434", "model_ids": ["qwen"]},
            {"id": "gliclass", "name": "GLiClass", "base_url": "http://127.0.0.1:8080", "model_ids": ["gli"]},
        ],
        keys={"typesafe": "ts-key"},
    )
    called = []

    class _Usage:
        input_tokens = None

    class _Result:
        def __init__(self, provider):
            self.provider = provider
            self.skipped = False
            self.skip_reason = None
            self.latency_ms = 1.5
            self.usage = _Usage()

    def fake_call(target):
        called.append(target["filter_provider"])
        return _Result(target["filter_provider"])

    monkeypatch.setattr(smoke, "call_provider", fake_call)
    assert smoke.main(["--db", str(db)]) == 0
    assert called == ["typesafe", "ollama", "gliclass"]
    out = capsys.readouterr().out
    assert "Manual only" in out
    assert "not CI" in out
