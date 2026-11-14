"""loom-agent known agent + runner registration."""
import sys

from daemon.known_agents import detect_installed, get_known_agents
from daemon.runners import RUNNERS, runnable_agents


def test_loom_agent_in_known_agents():
    names = {a["name"] for a in get_known_agents()}
    assert "loom-agent" in names


def test_loom_agent_always_detected():
    installed = detect_installed()
    assert installed.get("loom-agent") == "builtin"


def test_loom_agent_in_runners():
    assert "loom-agent" in runnable_agents()
    spec = RUNNERS["loom-agent"]
    assert spec.mode == "stdout"
    assert spec.binary == sys.executable
    argv = spec.build_argv("do the thing")
    assert "-m" in argv and "daemon.agent_run" in argv
    assert "--prompt" in argv


def test_agent_run_loads_key_from_settings_db(tmp_path, monkeypatch):
    import json
    import sqlite3
    from daemon.agent_run import load_llm_config_from_settings, resolve_llm_config

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
            json.dumps([{
                "id": "deepseek", "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
            }]),
            json.dumps({"deepseek": "sk-from-dashboard"}),
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    key, base, model = load_llm_config_from_settings(str(db))
    assert key == "sk-from-dashboard"
    assert "deepseek" in base
    assert model == "deepseek-chat"

    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    key2, _, _ = resolve_llm_config()
    assert key2 == "sk-from-dashboard"


def test_supervisor_loom_agent_env_injects_settings_key(tmp_path, monkeypatch):
    import json
    import sqlite3
    from daemon.supervisor import WorkerSupervisor

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
            json.dumps([{
                "id": "deepseek", "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
            }]),
            json.dumps({"deepseek": "sk-injected"}),
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_API_KEY"] == "sk-injected"
    assert env["DEEPSEEK_API_KEY"] == "sk-injected"
