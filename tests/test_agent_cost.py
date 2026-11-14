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
    assert "n/a" not in priced


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
    assert body["llm_total_tokens"] == 52
    assert body["accepted"] == 1
    assert body["escalation_rate"] == 1.0
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
