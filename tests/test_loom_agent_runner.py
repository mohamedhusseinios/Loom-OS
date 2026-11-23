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
    assert creds.active_chat_provider_id() == "deepseek"
    assert key == "sk-custom-endpoint"
    assert base == "https://proxy.example.com/v1"
    assert model == "gpt-4o-mini"
    assert style == "openai"


def test_llm_from_stored_resolves_openai_compatible_model():
    from daemon.agent_credentials import StoredAgentCredentials

    creds = StoredAgentCredentials(
        default_model="llama-3.1-8b",
        chat_provider="openrouter",
        providers=[
            {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"], "kind": "builtin"},
            {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"},
        ],
        keys={"deepseek": "sk-deep", "openrouter": "sk-or"},
    )
    assert creds.llm_from_stored() == ("sk-or", "https://openrouter.ai/api/v1", "llama-3.1-8b", "openai")
    assert creds.active_chat_provider_id() == "openrouter"


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
    assert kinds == {"groq": "openai_compatible", "deepseek": "builtin", "openai": "builtin", "anthropic": "builtin", "typesafe": "builtin", "openrouter_jev": "builtin", "ollama": "builtin", "gliclass": "builtin"}


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
    assert creds.llm_from_stored() == ("sk-deep", "https://api.deepseek.com", "jev-latest", "openai")
    assert creds.active_chat_provider_id() == "deepseek"



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


def _write_keyless_custom_db(tmp_path):
    db = tmp_path / "state.db"
    _write_settings_db(
        db,
        model="llama-3.1-8b",
        chat_provider="local-llm",
        providers=[
            {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_ids": ["deepseek-chat"]},
            {"id": "local-llm", "name": "Local", "base_url": "http://localhost:9000/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"},
        ],
        keys={"deepseek": "sk-stored-deepseek"},
    )
    return db


def test_llm_from_stored_returns_provider_id():
    from daemon.agent_credentials import StoredAgentCredentials

    custom = StoredAgentCredentials(
        default_model="llama-3.1-8b",
        providers=[{"id": "groq", "name": "Groq", "base_url": "https://g.example/v1", "model_ids": ["llama-3.1-8b"], "kind": "openai_compatible"}],
        keys={},
    )
    assert custom.llm_from_stored() == ("", "https://g.example/v1", "llama-3.1-8b", "openai")
    assert custom.active_chat_provider_id() == "groq"
    fallback = StoredAgentCredentials(default_model="x", providers=[], keys={"deepseek": "sk-d"})
    assert fallback.llm_from_stored() == ("sk-d", "https://api.deepseek.com", "x", "openai")
    assert fallback.active_chat_provider_id() == "deepseek"


def test_keyless_custom_provider_does_not_receive_deepseek_env_key_in_runtime(tmp_path, monkeypatch):
    from daemon.agent_credentials import load_stored_credentials, resolve_deepseek_key

    db = _write_keyless_custom_db(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    creds = load_stored_credentials(str(db))
    stored_key, base, _, _ = creds.llm_from_stored()
    provider_id = creds.active_chat_provider_id()
    assert provider_id == "local-llm"
    assert base == "http://localhost:9000/v1"
    assert stored_key == ""
    assert resolve_deepseek_key(stored_key) == "sk-process-env"  # helper alone still falls back; callers must gate

    from daemon.agent_credentials import resolve_chat_key
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-process")
    assert resolve_chat_key(provider_id, stored_key) == ""
    assert resolve_chat_key("deepseek", "") == "sk-loom-process"
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    assert resolve_chat_key("deepseek", "") == "sk-process-env"
    assert resolve_chat_key("deepseek", "sk-stored") == "sk-stored"
    assert resolve_chat_key("local-llm", "sk-custom") == "sk-custom"


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
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-process")
    monkeypatch.delenv("LOOM_AGENT_PROVIDER", raising=False)
    key, base, model, _ = resolve_llm_config()
    assert key == ""
    assert base == "http://localhost:9000/v1"
    assert model == "llama-3.1-8b"


def test_resolve_llm_config_supervisor_provider_env_blocks_deepseek_fallback(tmp_path, monkeypatch):
    from daemon.agent_run import resolve_llm_config

    monkeypatch.setenv("LOOM_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.setenv("LOOM_AGENT_PROVIDER", "local-llm")
    monkeypatch.setenv("LOOM_AGENT_BASE_URL", "http://localhost:9000/v1")
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-process")
    key, base, _, _ = resolve_llm_config()
    assert key == ""
    assert base == "http://localhost:9000/v1"


def test_resolve_llm_config_deepseek_env_fallback_still_works(tmp_path, monkeypatch):
    from daemon.agent_run import resolve_llm_config

    monkeypatch.setenv("LOOM_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-process-env")
    monkeypatch.delenv("LOOM_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_AGENT_PROVIDER", raising=False)
    key, _, _, _ = resolve_llm_config()
    assert key == "sk-process-env"


def test_run_manifest_keyless_custom_posts_openai_v1_root(tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock, patch
    from daemon.agent_run import run_manifest

    manifest = {
        "prompt": "say hi",
        "model": "llama",
        "run_dir": str(tmp_path / "run"),
        "events_path": str(tmp_path / "run" / "events.jsonl"),
        "worktree": str(tmp_path),
        "step_limit": 2,
        "token_limit": 1000,
        "cost_limit_usd": 1,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("LOOM_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("LOOM_AGENT_PROVIDER", "local-llm")
    monkeypatch.setenv("LOOM_AGENT_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOOM_AGENT_MODEL", "llama")
    monkeypatch.setenv("LOOM_AGENT_API_KEY", "sk-loom-process")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-not-be-sent")
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        body = json.dumps({
            "choices": [{"message": {"content": '{"thought":"ok","tool":null,"done":true}'}}],
            "usage": {},
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("daemon.llm_client._open_http", side_effect=fake_urlopen):
        code = run_manifest(str(path))
    assert code == 0
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["auth"] is None
