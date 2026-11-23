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


def test_loom_agent_in_runners(monkeypatch):
    monkeypatch.delenv("LOOM_AGENT_MANIFEST", raising=False)
    assert "loom-agent" in runnable_agents()
    spec = RUNNERS["loom-agent"]
    assert spec.mode == "stdout"
    assert spec.binary == sys.executable
    argv = spec.build_argv("do the thing")
    assert "-m" in argv and "daemon.agent_run" in argv
    assert "--prompt" in argv
    assert argv[argv.index("--prompt") + 1] == "do the thing"


def test_loom_agent_argv_uses_manifest_env(monkeypatch):
    monkeypatch.setenv("LOOM_AGENT_MANIFEST", "/tmp/run/manifest.json")
    argv = RUNNERS["loom-agent"].build_argv("do the thing")
    assert argv == ["-m", "daemon.agent_run", "--manifest", "/tmp/run/manifest.json"]


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
    key, base, model, provider_id = load_llm_config_from_settings(str(db))
    assert provider_id == "deepseek"
    assert key == "sk-from-dashboard"
    assert "deepseek" in base
    assert model == "deepseek-chat"

    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    key2, _, _ = resolve_llm_config()
    assert key2 == "sk-from-dashboard"


def test_llm_from_stored_uses_custom_deepseek_base_url_for_unlisted_model():
    """Settings UI keeps model_ids=deepseek-chat while default_model can be custom."""
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="gpt-4o-mini",
        providers=[{
            "id": "deepseek", "name": "DeepSeek",
            "base_url": "https://proxy.example.com/v1",
            "model_ids": ["deepseek-chat"],
        }],
        keys={"deepseek": "sk-custom-endpoint"},
    )
    key, base, model, provider_id = creds.llm_from_stored()
    assert provider_id == "deepseek"
    assert key == "sk-custom-endpoint"
    assert base == "https://proxy.example.com/v1"
    assert model == "gpt-4o-mini"


def test_llm_from_stored_resolves_openai_compatible_model():
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="llama-3.1-8b",
        providers=[
            {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"], "kind": "builtin"},
            {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"},
        ],
        keys={"deepseek": "sk-deep", "openrouter": "sk-or"},
    )
    assert creds.llm_from_stored() == ("sk-or", "https://openrouter.ai/api/v1", "llama-3.1-8b", "openrouter")


def test_merge_providers_preserves_custom_openai_compatible():
    from daemon.agent_credentials import merge_providers

    merged = merge_providers([], [{"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1", "model_ids": ["llama-3.1-70b"], "kind": "openai_compatible"}])
    groq = next(p for p in merged if p["id"] == "groq")
    assert groq["kind"] == "openai_compatible"
    assert "deepseek" in {p["id"] for p in merged}


def test_is_valid_custom_provider_id():
    from daemon.agent_credentials import is_valid_custom_provider_id

    assert is_valid_custom_provider_id("openrouter") is True
    assert is_valid_custom_provider_id("ollama") is False
    assert is_valid_custom_provider_id("A") is False


def test_normalize_provider_kind_and_defaults():
    from daemon.agent_credentials import ensure_default_providers, normalize_provider_kind

    assert normalize_provider_kind({"id": "deepseek", "kind": "openai_compatible"})["kind"] == "builtin"
    assert normalize_provider_kind({"id": "groq", "kind": None})["kind"] == "openai_compatible"
    assert normalize_provider_kind({"id": "groq"})["kind"] == "openai_compatible"
    kinds = {p["id"]: p["kind"] for p in ensure_default_providers([{"id": "groq", "name": "Groq", "base_url": "https://x", "model_ids": []}])}
    assert kinds == {"groq": "openai_compatible", "deepseek": "builtin", "typesafe": "builtin", "ollama": "builtin", "gliclass": "builtin"}


def test_llm_from_stored_ignores_builtin_non_deepseek_model_match():
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="jev-latest",
        providers=[
            {"id": "typesafe", "name": "TypeSafe", "base_url": "https://ts.example", "model_ids": ["jev-latest"], "kind": "builtin"},
            {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"], "kind": "builtin"},
        ],
        keys={"typesafe": "sk-ts", "deepseek": "sk-deep"},
    )
    assert creds.llm_from_stored() == ("sk-deep", "https://api.deepseek.com", "jev-latest", "deepseek")


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


def test_supervisor_loom_agent_env_overrides_process_deepseek_key(tmp_path, monkeypatch):
    """Dashboard BYOK must win over a daemon-process DEEPSEEK_API_KEY."""
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
            json.dumps({"deepseek": "sk-dashboard"}),
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_API_KEY"] == "sk-dashboard"
    assert env["DEEPSEEK_API_KEY"] == "sk-dashboard"


def test_resolve_llm_config_prefers_settings_over_deepseek_env(tmp_path, monkeypatch):
    import json
    import sqlite3
    from daemon.agent_run import resolve_llm_config

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
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    key, _, _ = resolve_llm_config()
    assert key == "sk-from-dashboard"


def _write_keyless_custom_db(tmp_path):
    import json
    import sqlite3

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
            "llama-3.1-8b",
            json.dumps([
                {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]},
                {"id": "local-llm", "name": "Local", "base_url": "http://localhost:9000/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"},
            ]),
            json.dumps({"deepseek": "sk-stored-deepseek"}),
        ),
    )
    conn.commit()
    conn.close()
    return db


def test_llm_from_stored_returns_provider_id():
    from daemon.agent_credentials import StoredAgentCredentials

    custom = StoredAgentCredentials(
        default_model="llama-3.1-8b",
        providers=[{"id": "groq", "name": "Groq", "base_url": "https://g.example/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"}],
        keys={},
    )
    assert custom.llm_from_stored() == ("", "https://g.example/v1", "llama-3.1-8b", "groq")
    fallback = StoredAgentCredentials(default_model="x", providers=[], keys={"deepseek": "sk-d"})
    assert fallback.llm_from_stored() == ("sk-d", "https://api.deepseek.com", "x", "deepseek")


def test_keyless_custom_provider_does_not_receive_deepseek_env_key_in_runtime(tmp_path, monkeypatch):
    from daemon.agent_credentials import load_stored_credentials, resolve_deepseek_key

    db = _write_keyless_custom_db(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    stored_key, base, _, provider_id = load_stored_credentials(str(db)).llm_from_stored()
    assert provider_id == "local-llm"
    assert base == "http://localhost:9000/v1"
    assert stored_key == ""
    assert resolve_deepseek_key(stored_key) == "sk-process-env"  # helper alone still falls back; callers must gate

    from daemon.agent_runtime import AgentRuntime
    assert AgentRuntime._resolve_chat_key(stored_key, provider_id) == ""
    assert AgentRuntime._resolve_chat_key("", "deepseek") == "sk-process-env"
    assert AgentRuntime._resolve_chat_key("sk-stored", "deepseek") == "sk-stored"
    assert AgentRuntime._resolve_chat_key("sk-custom", "local-llm") == "sk-custom"


def test_supervisor_env_keyless_custom_provider_drops_deepseek_key(tmp_path, monkeypatch):
    from daemon.supervisor import WorkerSupervisor

    db = _write_keyless_custom_db(tmp_path)
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-leftover")
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_PROVIDER"] == "local-llm"
    assert env["LOOM_AGENT_BASE_URL"] == "http://localhost:9000/v1"
    assert env["LOOM_AGENT_MODEL"] == "llama-3.1-8b"
    assert "DEEPSEEK_API_KEY" not in env
    assert env.get("LOOM_AGENT_API_KEY", "") == ""


def test_supervisor_env_custom_provider_uses_own_stored_key(tmp_path, monkeypatch):
    import json
    import sqlite3
    from daemon.supervisor import WorkerSupervisor

    db = _write_keyless_custom_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE agent_settings SET api_keys_json = ?", (json.dumps({"deepseek": "sk-d", "local-llm": "sk-local"}),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    env = WorkerSupervisor._loom_agent_env()
    assert env["LOOM_AGENT_API_KEY"] == "sk-local"
    assert "DEEPSEEK_API_KEY" not in env


def test_resolve_llm_config_keyless_custom_ignores_deepseek_env(tmp_path, monkeypatch):
    from daemon.agent_run import resolve_llm_config

    db = _write_keyless_custom_db(tmp_path)
    monkeypatch.setenv("LOOM_DB_PATH", str(db))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_PROVIDER", raising=False)
    key, base, model = resolve_llm_config()
    assert key == ""
    assert base == "http://localhost:9000/v1"
    assert model == "llama-3.1-8b"


def test_resolve_llm_config_supervisor_provider_env_blocks_deepseek_fallback(tmp_path, monkeypatch):
    from daemon.agent_run import resolve_llm_config

    monkeypatch.setenv("LOOM_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.setenv("LOOM_AGENT_PROVIDER", "local-llm")
    monkeypatch.setenv("LOOM_AGENT_BASE_URL", "http://localhost:9000/v1")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    key, base, _ = resolve_llm_config()
    assert key == ""
    assert base == "http://localhost:9000/v1"


def test_resolve_llm_config_deepseek_env_fallback_still_works(tmp_path, monkeypatch):
    from daemon.agent_run import resolve_llm_config

    monkeypatch.setenv("LOOM_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_PROVIDER", raising=False)
    key, _, _ = resolve_llm_config()
    assert key == "sk-process-env"
