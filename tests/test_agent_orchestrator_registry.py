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
async def test_default_settings_mask_empty_keys(reg, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    settings = await reg.get_agent_settings()
    assert settings.default_model == "deepseek-chat"
    assert any(p.id == "deepseek" for p in settings.providers)
    assert any(p.id == "typesafe" for p in settings.providers)
    assert settings.has_keys.get("deepseek") is False
    assert settings.has_keys.get("typesafe") is False
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
    assert settings.has_keys["deepseek"] is True
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
async def test_legacy_suggestion_tokens_not_mapped_to_filter(tmp_path):
    """Old jev_input_tokens copy into legacy_decision_input_tokens only.

    New per-role token columns stay NULL. Do not copy into filter_input_tokens.
    """
    import aiosqlite
    db_path = str(tmp_path / "legacy-suggestions.db")
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
                jev_input_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute(
            "INSERT INTO task_suggestions"
            " (id, project, task_id, action_id, action_label, jev_skipped,"
            " jev_input_tokens, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("s-old", "proj", "t1", "move_ready", "Move", 1, 42, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        await db.commit()

    registry = AgentRegistry(db_path)
    await registry.initialize()
    try:
        cursor = await registry.db.execute("PRAGMA table_info(task_suggestions)")
        cols = {r[1] for r in await cursor.fetchall()}
        assert "jev_skipped" in cols
        assert "jev_input_tokens" in cols
        assert "filter_input_tokens" in cols
        assert "judgment_input_tokens" in cols
        assert "legacy_decision_input_tokens" in cols
        cursor = await registry.db.execute(
            "SELECT jev_skipped, jev_input_tokens, filter_provider, filter_model,"
            " judgment_provider, judgment_model, filter_skipped, judgment_skipped,"
            " filter_skip_reason, judgment_skip_reason, filter_input_tokens,"
            " judgment_input_tokens, filter_latency_ms, judgment_latency_ms,"
            " effective_thresholds_json, legacy_decision_input_tokens"
            " FROM task_suggestions WHERE id = ?",
            ("s-old",),
        )
        row = await cursor.fetchone()
        assert row["jev_skipped"] == 1
        assert row["jev_input_tokens"] == 42
        assert row["legacy_decision_input_tokens"] == 42
        for name in (
            "filter_provider", "filter_model", "judgment_provider", "judgment_model",
            "filter_skipped", "judgment_skipped", "filter_skip_reason",
            "judgment_skip_reason", "filter_input_tokens", "judgment_input_tokens",
            "filter_latency_ms", "judgment_latency_ms", "effective_thresholds_json",
        ):
            assert row[name] is None, name
        loaded = await registry.get_task_suggestion("s-old")
        assert loaded is not None
        assert loaded.jev_input_tokens == 42
        assert loaded.jev_skipped is True
        assert loaded.legacy_decision_input_tokens == 42
        assert loaded.filter_input_tokens is None
        assert loaded.judgment_input_tokens is None
    finally:
        await registry.close()


@pytest.mark.asyncio
async def test_new_suggestion_does_not_copy_jev_tokens_into_filter(reg):
    sug = await reg.create_task_suggestion(
        "proj", "t1", "loom.move_ready", "Move to Ready", 0.9, "go", [],
        jev_input_tokens=22,
        filter_provider="ollama",
        filter_model="nimble",
        filter_input_tokens=7,
        judgment_provider="typesafe",
        judgment_model="jev-latest",
        judgment_input_tokens=9,
        filter_skipped=False,
        judgment_skipped=True,
        judgment_skip_reason="timeout",
        filter_latency_ms=12.5,
        judgment_latency_ms=3.0,
        effective_thresholds_json='{"keep": 0.8}',
    )
    loaded = await reg.get_task_suggestion(sug.id)
    assert loaded.jev_input_tokens == 22
    assert loaded.legacy_decision_input_tokens is None
    assert loaded.filter_input_tokens == 7
    assert loaded.judgment_input_tokens == 9
    assert loaded.filter_provider == "ollama"
    assert loaded.filter_model == "nimble"
    assert loaded.judgment_provider == "typesafe"
    assert loaded.judgment_model == "jev-latest"
    assert loaded.filter_skipped is False
    assert loaded.judgment_skipped is True
    assert loaded.judgment_skip_reason == "timeout"
    assert loaded.filter_latency_ms == 12.5
    assert loaded.judgment_latency_ms == 3.0
    assert loaded.effective_thresholds_json == '{"keep": 0.8}'


@pytest.mark.asyncio
async def test_settings_roles_and_default_decision_providers(reg):
    settings = await reg.get_agent_settings()
    ids = {p.id for p in settings.providers}
    assert "ollama" in ids
    assert "gliclass" in ids
    ollama = next(p for p in settings.providers if p.id == "ollama")
    assert ollama.base_url == "http://localhost:11434"
    assert settings.filter_provider is None
    assert settings.judgment_provider is None
    assert settings.threshold_overrides is None
    assert settings.selection_autonomy_enabled is True
    assert settings.autonomy_min_fit == "High"
    assert settings.autonomy_require_margin is True

    # Schema stores gliclass-as-judgment; API rejection is a later task.
    updated = await reg.update_agent_settings(AgentSettingsUpdate(
        filter_provider="gliclass",
        judgment_provider="gliclass",
        threshold_overrides={"ollama": {"drop": 0.2, "mid": 0.5, "keep": 0.8}},
        selection_autonomy_enabled=False,
        autonomy_min_fit="Low",
        autonomy_require_margin=False,
    ))
    assert updated.filter_provider == "gliclass"
    assert updated.judgment_provider == "gliclass"
    assert updated.threshold_overrides["ollama"]["keep"] == 0.8
    assert updated.selection_autonomy_enabled is False
    assert updated.autonomy_min_fit == "Low"
    assert updated.autonomy_require_margin is False
    again = await reg.get_agent_settings()
    assert again.filter_provider == "gliclass"
    assert again.judgment_provider == "gliclass"
    assert again.threshold_overrides == {"ollama": {"drop": 0.2, "mid": 0.5, "keep": 0.8}}

    kept = await reg.update_agent_settings(AgentSettingsUpdate(default_model="deepseek-chat"))
    assert kept.filter_provider == "gliclass"
    assert kept.judgment_provider == "gliclass"
    assert kept.threshold_overrides["ollama"]["drop"] == 0.2
    assert kept.selection_autonomy_enabled is False
    assert kept.autonomy_min_fit == "Low"
    assert kept.autonomy_require_margin is False


@pytest.mark.asyncio
async def test_legacy_settings_gain_role_columns_without_forced_defaults(tmp_path):
    import json
    import aiosqlite
    db = tmp_path / "legacy-settings.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "CREATE TABLE agent_settings ("
            " id INTEGER PRIMARY KEY, default_model TEXT,"
            " providers_json TEXT, api_keys_json TEXT)"
        )
        await conn.execute(
            "INSERT INTO agent_settings VALUES (1, ?, ?, ?)",
            (
                "deepseek-chat",
                json.dumps([{
                    "id": "deepseek", "name": "DeepSeek",
                    "base_url": "https://api.deepseek.com",
                    "model_ids": ["deepseek-chat"],
                }]),
                "{}",
            ),
        )
        await conn.commit()

    reg = AgentRegistry(str(db))
    await reg.initialize()
    try:
        cursor = await reg.db.execute("PRAGMA table_info(agent_settings)")
        cols = {r[1] for r in await cursor.fetchall()}
        assert {
            "filter_provider", "judgment_provider", "threshold_overrides_json",
            "selection_autonomy_enabled", "autonomy_min_fit", "autonomy_require_margin",
        } <= cols
        cursor = await reg.db.execute(
            "SELECT filter_provider, judgment_provider, threshold_overrides_json,"
            " selection_autonomy_enabled, autonomy_min_fit, autonomy_require_margin"
            " FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        assert row["filter_provider"] is None
        assert row["judgment_provider"] is None
        assert row["threshold_overrides_json"] is None
        assert row["selection_autonomy_enabled"] == 1
        assert row["autonomy_min_fit"] == "High"
        assert row["autonomy_require_margin"] == 1
        settings = await reg.get_agent_settings()
        ids = {p.id for p in settings.providers}
        assert {"deepseek", "typesafe", "ollama", "gliclass"} <= ids
        assert settings.filter_provider is None
        assert settings.judgment_provider is None
        assert settings.selection_autonomy_enabled is True
        assert settings.autonomy_min_fit == "High"
        assert settings.autonomy_require_margin is True
    finally:
        await reg.close()


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


@pytest.mark.asyncio
async def test_typesafe_provider_migrated_and_keys_cleared(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    import json
    import aiosqlite
    db = tmp_path / "legacy.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "CREATE TABLE agent_settings ("
            " id INTEGER PRIMARY KEY, default_model TEXT,"
            " providers_json TEXT, api_keys_json TEXT)"
        )
        await conn.execute(
            "INSERT INTO agent_settings VALUES (1, ?, ?, ?)",
            (
                "deepseek-chat",
                json.dumps([{
                    "id": "deepseek", "name": "DeepSeek",
                    "base_url": "https://api.deepseek.com",
                    "model_ids": ["deepseek-chat"],
                }]),
                json.dumps({"deepseek": "sk-legacy-1111"}),
            ),
        )
        await conn.commit()

    # The file above is not a full loom db; AgentRegistry.initialize creates
    # remaining tables and must migrate the typesafe provider into the row.
    from daemon.registry import AgentRegistry
    from daemon.models import AgentSettingsUpdate
    reg = AgentRegistry(str(db))
    await reg.initialize()
    try:
        settings = await reg.get_agent_settings()
        ids = {p.id for p in settings.providers}
        assert "deepseek" in ids
        assert "typesafe" in ids
        assert settings.has_keys["deepseek"] is True
        assert settings.has_keys["typesafe"] is False
        await reg.update_agent_settings(AgentSettingsUpdate(
            api_keys={"typesafe": "jev-legacy-2222"},
            providers=[{
                "id": "typesafe", "name": "TypeSafe (Jev)",
                "base_url": "http://localhost:11434", "model_ids": ["jev-latest"],
            }],
        ))
        settings = await reg.get_agent_settings()
        assert settings.has_keys["typesafe"] is True
        assert settings.api_keys_masked["typesafe"] == "••••2222"
        raw = await reg.get_raw_api_keys()
        assert raw["typesafe"] == "jev-legacy-2222"
        await reg.update_agent_settings(AgentSettingsUpdate(api_keys={"typesafe": ""}))
        settings = await reg.get_agent_settings()
        assert settings.has_keys["typesafe"] is False
        raw = await reg.get_raw_api_keys()
        assert "typesafe" not in raw
        assert raw["deepseek"] == "sk-legacy-1111"
    finally:
        await reg.close()
