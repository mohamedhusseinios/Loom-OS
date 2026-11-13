"""Registry CRUD for Loom agent settings, chats, and suggestions."""
import pytest

from daemon.models import AgentSettingsUpdate, SuggestionStatus
from daemon.registry import AgentRegistry


@pytest.fixture
async def reg(tmp_path):
    registry = AgentRegistry(str(tmp_path / "state.db"))
    await registry.initialize()
    yield registry
    await registry.close()


@pytest.mark.asyncio
async def test_default_settings_mask_empty_keys(reg):
    settings = await reg.get_agent_settings()
    assert settings.default_model == "deepseek-chat"
    assert any(p.id == "deepseek" for p in settings.providers)
    assert settings.api_keys_masked == {} or all(
        (v is None or v.startswith("••••")) for v in settings.api_keys_masked.values()
    )


@pytest.mark.asyncio
async def test_update_settings_stores_key_masked_on_read(reg):
    await reg.update_agent_settings(AgentSettingsUpdate(
        api_keys={"deepseek": "sk-test-secret-key-1234"},
    ))
    settings = await reg.get_agent_settings(mask_keys=True)
    assert settings.api_keys_masked["deepseek"] == "••••1234"
    raw = await reg.get_raw_api_keys()
    assert raw["deepseek"] == "sk-test-secret-key-1234"


@pytest.mark.asyncio
async def test_chat_and_messages(reg):
    chat = await reg.create_agent_chat("proj", task_id="t1")
    await reg.add_agent_message(chat.id, "user", "hello")
    await reg.add_agent_message(chat.id, "assistant", "hi")
    msgs = await reg.list_agent_messages(chat.id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].content == "hi"


@pytest.mark.asyncio
async def test_single_pending_suggestion_per_task(reg):
    s1 = await reg.create_task_suggestion(
        "proj", "t1", "move_ready", "Move to Ready", 0.9, "do it", [{"id": "move_ready"}],
    )
    assert s1.status == SuggestionStatus.PENDING
    s2 = await reg.create_task_suggestion(
        "proj", "t1", "move_blocked", "Move to Blocked", 0.5, "block", [],
    )
    old = await reg.get_task_suggestion(s1.id)
    assert old.status == SuggestionStatus.DISMISSED
    pending = await reg.get_pending_suggestion("t1")
    assert pending is not None
    assert pending.id == s2.id
