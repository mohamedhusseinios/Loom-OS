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


@pytest.mark.asyncio
async def test_list_agent_messages_returns_latest(reg):
    chat = await reg.create_agent_chat("proj")
    for i in range(5):
        await reg.add_agent_message(chat.id, "user", f"m{i}")
    msgs = await reg.list_agent_messages(chat.id, limit=3)
    assert [m.content for m in msgs] == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_suggestion_persists_usage_and_escalated(reg):
    sug = await reg.create_task_suggestion(
        "proj", "t1", "loom.move_ready", "Move to Ready", 0.91, "Suggested next step: Move to Ready",
        [{"id": "loom.move_ready"}],
        jev_skipped=False,
        jev_input_tokens=22,
        llm_prompt_tokens=40,
        llm_completion_tokens=12,
        escalated=True,
    )
    loaded = await reg.get_task_suggestion(sug.id)
    assert loaded.jev_input_tokens == 22
    assert loaded.llm_prompt_tokens == 40
    assert loaded.llm_completion_tokens == 12
    assert loaded.escalated is True
    updated = await reg.set_suggestion_status(sug.id, SuggestionStatus.ACCEPTED)
    assert updated.status == SuggestionStatus.ACCEPTED
    assert updated.jev_input_tokens == 22
    assert updated.escalated is True


@pytest.mark.asyncio
async def test_task_suggestions_columns_migrate_on_initialize(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE task_suggestions (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                task_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                action_label TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                prose TEXT NOT NULL DEFAULT '',
                catalog_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                jev_skipped INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()
    registry = AgentRegistry(db_path)
    await registry.initialize()
    cursor = await registry.db.execute("PRAGMA table_info(task_suggestions)")
    cols = {r[1] for r in await cursor.fetchall()}
    assert {"jev_input_tokens", "llm_prompt_tokens", "llm_completion_tokens", "escalated", "context_hash"} <= cols
    await registry.close()


@pytest.mark.asyncio
async def test_suggestion_persists_context_hash(reg):
    sug = await reg.create_task_suggestion(
        "proj", "t1", "loom.move_ready", "Move to Ready", 0.9, "go", [],
        context_hash="abc123",
    )
    loaded = await reg.get_task_suggestion(sug.id)
    assert loaded.context_hash == "abc123"
    summary = await reg.suggestion_cost_summary("proj")
    assert summary["suggestion_count"] == 1
    assert summary["pending"] == 1
