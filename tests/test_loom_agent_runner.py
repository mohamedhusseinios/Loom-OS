"""loom-agent known agent + runner registration."""
import json
import sqlite3
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


def _write_settings_db(db, *, model="deepseek-chat", providers=None, keys=None, chat_provider=None):
    conn = sqlite3.connect(db)
    cols = "id INTEGER PRIMARY KEY, default_model TEXT, providers_json TEXT, api_keys_json TEXT"
    if chat_provider is not None:
        cols = "id INTEGER PRIMARY KEY, default_model TEXT, chat_provider TEXT, providers_json TEXT, api_keys_json TEXT"
    conn.execute(f"CREATE TABLE agent_settings ({cols})")
    providers = providers or [{
        "id": "deepseek", "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model_ids": ["deepseek-chat"],
        "api_style": "openai",
    }]
    keys = keys or {"deepseek": "sk-from-dashboard"}
    if chat_provider is not None:
        conn.execute(
            "INSERT INTO agent_settings VALUES (1, ?, ?, ?, ?)",
            (model, chat_provider, json.dumps(providers), json.dumps(keys)),
        )
    else:
        conn.execute(
            "INSERT INTO agent_settings VALUES (1, ?, ?, ?)",
            (model, json.dumps(providers), json.dumps(keys)),
        )
    conn.commit()
    conn.close()


def test_agent_run_loads_key_from_settings_db(tmp_path, monkeypatch):
    from daemon.agent_run import load_llm_config_from_settings, resolve_llm_config

    db = tmp_path / "state.db"
    _write_settings_db(db)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    key, base, model, style, provider_id = load_llm_config_from_settings(str(db))
    assert key == "sk-from-dashboard"
    assert "deepseek" in base
    assert model == "deepseek-chat"
    assert style == "openai"
    assert provider_id == "deepseek"

    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    key2, _, _, _ = resolve_llm_config()
    assert key2 == "sk-from-dashboard"


def test_llm_from_stored_uses_custom_deepseek_base_url_for_unlisted_model():
    """Active chat provider base_url applies even when default_model is unlisted."""
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="gpt-4o-mini",
        chat_provider="deepseek",
        providers=[{
            "id": "deepseek", "name": "DeepSeek",
            "base_url": "https://proxy.example.com/v1",
            "model_ids": ["deepseek-chat"],
            "api_style": "openai",
        }],
        keys={"deepseek": "sk-custom-endpoint"},
    )
    key, base, model, style = creds.llm_from_stored()
    assert key == "sk-custom-endpoint"
    assert base == "https://proxy.example.com/v1"
    assert model == "gpt-4o-mini"
    assert style == "openai"


def test_llm_from_stored_respects_chat_provider_and_anthropic_style():
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="claude-sonnet-4-5",
        chat_provider="anthropic",
        providers=[
            {
                "id": "deepseek", "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
                "api_style": "openai",
            },
            {
                "id": "anthropic", "name": "Anthropic",
                "base_url": "https://api.anthropic.com",
                "model_ids": ["claude-sonnet-4-5"],
                "api_style": "anthropic",
            },
        ],
        keys={"anthropic": "sk-ant", "deepseek": "sk-ds"},
    )
    key, base, model, style = creds.llm_from_stored()
    assert key == "sk-ant"
    assert "anthropic" in base
    assert model == "claude-sonnet-4-5"
    assert style == "anthropic"


def test_llm_from_stored_custom_openai_provider():
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="llama-3",
        chat_provider="custom-abc",
        providers=[{
            "id": "custom-abc", "name": "Local",
            "base_url": "http://127.0.0.1:8080",
            "model_ids": ["llama-3"],
            "api_style": "openai",
        }],
        keys={"custom-abc": "sk-local"},
    )
    key, base, model, style = creds.llm_from_stored()
    assert key == "sk-local"
    assert base == "http://127.0.0.1:8080"
    assert model == "llama-3"
    assert style == "openai"


def test_supervisor_loom_agent_env_injects_settings_key(tmp_path, monkeypatch):
    from daemon.supervisor import WorkerSupervisor

    db = tmp_path / "state.db"
    _write_settings_db(db, keys={"deepseek": "sk-injected"})
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_API_KEY"] == "sk-injected"
    assert env["DEEPSEEK_API_KEY"] == "sk-injected"
    assert env["LOOM_AGENT_API_STYLE"] == "openai"


def test_supervisor_loom_agent_env_overrides_process_deepseek_key(tmp_path, monkeypatch):
    """Dashboard BYOK must win over a daemon-process DEEPSEEK_API_KEY."""
    from daemon.supervisor import WorkerSupervisor

    db = tmp_path / "state.db"
    _write_settings_db(db, keys={"deepseek": "sk-dashboard"})
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_API_KEY"] == "sk-dashboard"
    assert env["DEEPSEEK_API_KEY"] == "sk-dashboard"


def test_supervisor_anthropic_env_injection(tmp_path, monkeypatch):
    from daemon.supervisor import WorkerSupervisor

    db = tmp_path / "state.db"
    _write_settings_db(
        db,
        model="claude-sonnet-4-5",
        chat_provider="anthropic",
        providers=[{
            "id": "anthropic", "name": "Anthropic",
            "base_url": "https://api.anthropic.com",
            "model_ids": ["claude-sonnet-4-5"],
            "api_style": "anthropic",
        }],
        keys={"anthropic": "sk-ant-dash"},
    )
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_API_KEY"] == "sk-ant-dash"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-dash"
    assert env["LOOM_AGENT_API_STYLE"] == "anthropic"
    assert "DEEPSEEK_API_KEY" not in env or env.get("DEEPSEEK_API_KEY") != "sk-ant-dash"


def test_resolve_llm_config_prefers_settings_over_deepseek_env(tmp_path, monkeypatch):
    from daemon.agent_run import resolve_llm_config

    db = tmp_path / "state.db"
    _write_settings_db(db, keys={"deepseek": "sk-from-dashboard"})
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    key, _, _, style = resolve_llm_config()
    assert key == "sk-from-dashboard"
    assert style == "openai"
