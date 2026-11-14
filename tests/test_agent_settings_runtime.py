"""Dashboard settings resolve before env and are re-read every cycle."""
import pytest

from daemon.agent_credentials import resolve_deepseek_key, resolve_typesafe_key
from daemon.agent_runtime import AgentRuntime
from daemon.jev_client import resolve_systemone_url
from daemon.models import AgentSettingsUpdate
from daemon.registry import AgentRegistry


def test_resolve_helpers_settings_then_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env")
    assert resolve_deepseek_key("sk-settings") == "sk-settings"
    assert resolve_typesafe_key("ts-settings") == "ts-settings"
    assert resolve_deepseek_key("") == "sk-env"
    assert resolve_typesafe_key(None) == "ts-env"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert resolve_deepseek_key("") == ""
    assert resolve_typesafe_key("") == ""


@pytest.mark.asyncio
async def test_runtime_reads_updated_keys_without_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    reg = AgentRegistry(str(tmp_path / "state.db"))
    await reg.initialize()
    runtime = AgentRuntime(reg, graph_engine=None)
    try:
        llm, model = await runtime._llm_from_settings()
        jev = await runtime._jev_from_settings()
        assert llm.api_key == ""
        assert not jev.available
        assert model == "deepseek-chat"

        await reg.update_agent_settings(AgentSettingsUpdate(
            default_model="deepseek-chat",
            api_keys={"deepseek": "sk-first", "typesafe": "ts-first"},
            providers=[{
                "id": "typesafe", "name": "TypeSafe (Jev)",
                "base_url": "http://localhost:11434", "model_ids": ["jev-latest"],
            }],
        ))
        llm, _ = await runtime._llm_from_settings()
        jev = await runtime._jev_from_settings()
        assert llm.api_key == "sk-first"
        assert jev.api_key == "ts-first"
        assert jev.base_url == resolve_systemone_url("http://localhost:11434")

        # Env must not override a dashboard key (same order as DeepSeek runtime).
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
        monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env")
        llm, _ = await runtime._llm_from_settings()
        jev = await runtime._jev_from_settings()
        assert llm.api_key == "sk-first"
        assert jev.api_key == "ts-first"

        # Updating settings is picked up on the next call (no daemon restart).
        await reg.update_agent_settings(AgentSettingsUpdate(
            api_keys={"deepseek": "sk-second", "typesafe": "ts-second"},
        ))
        llm, _ = await runtime._llm_from_settings()
        jev = await runtime._jev_from_settings()
        assert llm.api_key == "sk-second"
        assert jev.api_key == "ts-second"

        # Clearing falls back to env.
        await reg.update_agent_settings(AgentSettingsUpdate(
            api_keys={"deepseek": "", "typesafe": ""},
        ))
        llm, _ = await runtime._llm_from_settings()
        jev = await runtime._jev_from_settings()
        assert llm.api_key == "sk-env"
        assert jev.api_key == "ts-env"
    finally:
        await reg.close()
