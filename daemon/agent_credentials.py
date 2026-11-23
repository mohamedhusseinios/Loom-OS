"""Resolve Loom Agent API keys from dashboard settings with env fallback.

Chat and decision keys are stored in ``agent_settings.api_keys_json`` as
plaintext — the existing BYOK path has no at-rest encryption. GET endpoints
must return only masked values plus ``has_keys`` booleans, never the raw
secret. Runtime reads settings on every cycle (no daemon restart).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

DEEPSEEK_PROVIDER_ID = "deepseek"
OPENAI_PROVIDER_ID = "openai"
ANTHROPIC_PROVIDER_ID = "anthropic"
TYPESAFE_PROVIDER_ID = "typesafe"
OPENROUTER_JEV_PROVIDER_ID = "openrouter_jev"
OLLAMA_PROVIDER_ID = "ollama"
GLICLASS_PROVIDER_ID = "gliclass"

API_STYLE_OPENAI = "openai"
API_STYLE_ANTHROPIC = "anthropic"
VALID_API_STYLES = frozenset({API_STYLE_OPENAI, API_STYLE_ANTHROPIC})

DECISION_PROVIDER_IDS = frozenset({TYPESAFE_PROVIDER_ID, OPENROUTER_JEV_PROVIDER_ID, OLLAMA_PROVIDER_ID, GLICLASS_PROVIDER_ID})

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_TYPESAFE_BASE_URL = "https://api.typesafe.ai"
DEFAULT_OPENROUTER_JEV_BASE_URL = "https://openrouter.ai/api"
DEFAULT_OPENROUTER_JEV_MODEL = "~typesafe/jev-latest"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

BUILTIN_PROVIDER_IDS: frozenset[str] = frozenset({DEEPSEEK_PROVIDER_ID, OPENAI_PROVIDER_ID, ANTHROPIC_PROVIDER_ID, TYPESAFE_PROVIDER_ID, OPENROUTER_JEV_PROVIDER_ID, OLLAMA_PROVIDER_ID, GLICLASS_PROVIDER_ID})
PROVIDER_KIND_BUILTIN = "builtin"
PROVIDER_KIND_OPENAI = "openai_compatible"

DEFAULT_DEEPSEEK_PROVIDER: dict[str, Any] = {
    "id": DEEPSEEK_PROVIDER_ID,
    "name": "DeepSeek",
    "base_url": DEFAULT_DEEPSEEK_BASE_URL,
    "model_ids": [DEFAULT_DEEPSEEK_MODEL],
    "api_style": API_STYLE_OPENAI,
}

DEFAULT_OPENAI_PROVIDER: dict[str, Any] = {
    "id": OPENAI_PROVIDER_ID,
    "name": "OpenAI",
    "base_url": DEFAULT_OPENAI_BASE_URL,
    "model_ids": ["gpt-4o-mini"],
    "api_style": API_STYLE_OPENAI,
}

DEFAULT_ANTHROPIC_PROVIDER: dict[str, Any] = {
    "id": ANTHROPIC_PROVIDER_ID,
    "name": "Anthropic",
    "base_url": DEFAULT_ANTHROPIC_BASE_URL,
    "model_ids": ["claude-sonnet-4-5"],
    "api_style": API_STYLE_ANTHROPIC,
}

DEFAULT_TYPESAFE_PROVIDER: dict[str, Any] = {
    "id": TYPESAFE_PROVIDER_ID,
    "name": "TypeSafe (Jev)",
    "base_url": "",
    "model_ids": ["jev-latest"],
    "api_style": API_STYLE_OPENAI,
}

DEFAULT_OPENROUTER_JEV_PROVIDER: dict[str, Any] = {
    "id": OPENROUTER_JEV_PROVIDER_ID,
    "name": "Jev (OpenRouter)",
    "base_url": DEFAULT_OPENROUTER_JEV_BASE_URL,
    "model_ids": [DEFAULT_OPENROUTER_JEV_MODEL],
    "api_style": API_STYLE_OPENAI,
}

DEFAULT_OLLAMA_PROVIDER: dict[str, Any] = {
    "id": OLLAMA_PROVIDER_ID,
    "name": "Ollama",
    "base_url": DEFAULT_OLLAMA_BASE_URL,
    "model_ids": [],
    "api_style": API_STYLE_OPENAI,
}

DEFAULT_GLICLASS_PROVIDER: dict[str, Any] = {
    "id": GLICLASS_PROVIDER_ID,
    "name": "GLiClass",
    "base_url": "",
    "model_ids": [],
    "api_style": API_STYLE_OPENAI,
}

DEFAULT_AGENT_PROVIDERS: tuple[dict[str, Any], ...] = (
    DEFAULT_DEEPSEEK_PROVIDER,
    DEFAULT_OPENAI_PROVIDER,
    DEFAULT_ANTHROPIC_PROVIDER,
    DEFAULT_TYPESAFE_PROVIDER,
    DEFAULT_OPENROUTER_JEV_PROVIDER,
    DEFAULT_OLLAMA_PROVIDER,
    DEFAULT_GLICLASS_PROVIDER,
)

CHAT_PRESET_IDS = frozenset({DEEPSEEK_PROVIDER_ID, OPENAI_PROVIDER_ID, ANTHROPIC_PROVIDER_ID})

_PROVIDER_ENV_KEYS = {
    DEEPSEEK_PROVIDER_ID: "DEEPSEEK_API_KEY",
    OPENAI_PROVIDER_ID: "OPENAI_API_KEY",
    ANTHROPIC_PROVIDER_ID: "ANTHROPIC_API_KEY",
}


def mask_key(raw: str | None) -> str | None:
    if not raw:
        return None
    if len(raw) <= 4:
        return "••••"
    return "••••" + raw[-4:]


def is_masked_key(value: str | None) -> bool:
    return bool(value) and str(value).startswith("••••")


def first_nonempty(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ""


def normalize_api_style(value: Any, provider_id: str = "") -> str:
    text = str(value or "").strip().lower()
    if text in VALID_API_STYLES:
        return text
    if provider_id == ANTHROPIC_PROVIDER_ID:
        return API_STYLE_ANTHROPIC
    return API_STYLE_OPENAI


def default_base_url_for(provider_id: str, api_style: str = API_STYLE_OPENAI) -> str:
    if provider_id == DEEPSEEK_PROVIDER_ID:
        return DEFAULT_DEEPSEEK_BASE_URL
    if provider_id == OPENAI_PROVIDER_ID:
        return DEFAULT_OPENAI_BASE_URL
    if provider_id == ANTHROPIC_PROVIDER_ID or api_style == API_STYLE_ANTHROPIC:
        return DEFAULT_ANTHROPIC_BASE_URL
    return DEFAULT_DEEPSEEK_BASE_URL


def is_chat_provider_id(provider_id: str) -> bool:
    return bool(provider_id) and provider_id not in DECISION_PROVIDER_IDS


def _as_provider_dict(provider: Any) -> dict[str, Any]:
    if hasattr(provider, "model_dump"):
        parsed = provider.model_dump()
    elif isinstance(provider, dict):
        parsed = dict(provider)
    else:
        raise TypeError(f"unsupported provider value: {type(provider)!r}")
    pid = parsed.get("id") or ""
    parsed["api_style"] = normalize_api_style(parsed.get("api_style"), pid)
    if "model_ids" not in parsed or parsed["model_ids"] is None:
        parsed["model_ids"] = []
    return parsed


def normalize_provider_kind(provider: dict[str, Any]) -> dict[str, Any]:
    """Set ``kind`` from the id when missing; built-in ids are always ``builtin``."""
    row = dict(provider)
    if (row.get("id") or "") in BUILTIN_PROVIDER_IDS:
        row["kind"] = PROVIDER_KIND_BUILTIN
    elif not row.get("kind"):
        row["kind"] = PROVIDER_KIND_OPENAI
    return row


def is_valid_custom_provider_id(provider_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_-]{2,}", provider_id or "")) and provider_id not in BUILTIN_PROVIDER_IDS


def ensure_default_providers(providers: list[Any] | None) -> list[dict[str, Any]]:
    """Keep existing providers and append built-in defaults if missing."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in providers or []:
        parsed = _as_provider_dict(item)
        pid = parsed.get("id") or ""
        if not pid:
            continue
        if pid not in by_id:
            order.append(pid)
        by_id[pid] = parsed
    for default in DEFAULT_AGENT_PROVIDERS:
        if default["id"] not in by_id:
            by_id[default["id"]] = dict(default)
            order.append(default["id"])
        else:
            # Fill missing api_style on legacy rows without clobbering user fields.
            current = by_id[default["id"]]
            if "api_style" not in current or not current.get("api_style"):
                current["api_style"] = default["api_style"]
    return [normalize_provider_kind(by_id[pid]) for pid in order]


def merge_providers(current: list[Any] | None, incoming: list[Any] | None) -> list[dict[str, Any]]:
    """Overwrite providers by id from ``incoming``; keep unspecified existing rows."""
    merged = ensure_default_providers(current)
    if not incoming:
        return merged
    by_id = {p["id"]: p for p in merged}
    order = [p["id"] for p in merged]
    for item in incoming:
        parsed = _as_provider_dict(item)
        pid = parsed.get("id") or ""
        if not pid:
            continue
        if pid not in by_id:
            order.append(pid)
        by_id[pid] = parsed
    return [normalize_provider_kind(by_id[pid]) for pid in order]


_DEFAULT_PROVIDER_IDS = frozenset(p["id"] for p in DEFAULT_AGENT_PROVIDERS)


def is_custom_chat_provider_id(provider_id: str) -> bool:
    """True for user-added chat providers (not built-in defaults / decision rows)."""
    return is_chat_provider_id(provider_id) and provider_id not in _DEFAULT_PROVIDER_IDS


def sync_providers_on_update(current: list[Any] | None, incoming: list[Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge ``incoming`` onto ``current``, dropping custom chat providers omitted from ``incoming``.

    Built-in defaults and decision providers still follow ``merge_providers`` (kept when
    omitted). Custom chat rows must be listed to survive a settings save, matching the
    dashboard's full chat-provider list. Returns ``(providers, removed_custom_ids)``.
    """
    before_ids = {p["id"] for p in ensure_default_providers(current)}
    merged = merge_providers(current, incoming)
    if not incoming:
        return merged, []
    incoming_ids: set[str] = set()
    for item in incoming:
        parsed = _as_provider_dict(item)
        pid = parsed.get("id") or ""
        if pid:
            incoming_ids.add(pid)
    kept: list[dict[str, Any]] = []
    removed: list[str] = []
    for provider in merged:
        pid = provider.get("id") or ""
        if is_custom_chat_provider_id(pid) and pid not in incoming_ids:
            removed.append(pid)
            continue
        kept.append(provider)
    # Also treat customs present before update but absent after as removed (keys cleanup).
    after_ids = {p["id"] for p in kept}
    for pid in before_ids - after_ids:
        if is_custom_chat_provider_id(pid) and pid not in removed:
            removed.append(pid)
    return kept, removed


def provider_base_url(providers: list[dict[str, Any]], provider_id: str, default: str = "") -> str:
    for provider in providers:
        if provider.get("id") == provider_id:
            return (provider.get("base_url") or "").strip() or default
    return default


def resolve_deepseek_key(settings_key: str | None) -> str:
    """Dashboard settings first, then ``DEEPSEEK_API_KEY`` (existing runtime order)."""
    return first_nonempty(settings_key, os.environ.get("DEEPSEEK_API_KEY", ""))


def resolve_chat_key(provider_id: str, settings_key: str | None) -> str:
    """Settings key, then preset env. ``LOOM_AGENT_API_KEY`` only for built-in chat ids.

    Custom endpoints must not inherit the daemon process key when their row has none.
    """
    env_name = _PROVIDER_ENV_KEYS.get(provider_id)
    loom_key = "" if is_custom_chat_provider_id(provider_id) else os.environ.get("LOOM_AGENT_API_KEY", "")
    preset_key = os.environ.get(env_name, "") if env_name else ""
    return first_nonempty(settings_key, loom_key, preset_key)


def resolve_typesafe_key(settings_key: str | None) -> str:
    """Dashboard settings first, then ``TYPESAFE_API_KEY``."""
    return first_nonempty(settings_key, os.environ.get("TYPESAFE_API_KEY", ""))


def resolve_typesafe_base_url(settings_url: str | None) -> str | None:
    """Non-empty settings URL wins; otherwise ``None`` so JevClient uses env/default."""
    if settings_url and str(settings_url).strip():
        return str(settings_url).strip()
    return None


@dataclass
class StoredAgentCredentials:
    default_model: str = DEFAULT_DEEPSEEK_MODEL
    providers: list[dict[str, Any]] = field(default_factory=list)
    keys: dict[str, str] = field(default_factory=dict)
    chat_provider: str = DEEPSEEK_PROVIDER_ID

    @property
    def deepseek_key(self) -> str:
        return self.keys.get(DEEPSEEK_PROVIDER_ID, "") or ""

    @property
    def typesafe_key(self) -> str:
        return self.keys.get(TYPESAFE_PROVIDER_ID, "") or ""

    @property
    def typesafe_base_url(self) -> str:
        return provider_base_url(self.providers, TYPESAFE_PROVIDER_ID, "")

    def _provider_by_id(self) -> dict[str, dict[str, Any]]:
        return {p.get("id"): p for p in self.providers if p.get("id")}

    def resolve_chat_provider_row(self) -> dict[str, Any]:
        """Pick the active chat provider row (never a decision-only id)."""
        by_id = self._provider_by_id()
        chat_id = (self.chat_provider or "").strip()
        if chat_id and is_chat_provider_id(chat_id) and chat_id in by_id:
            return by_id[chat_id]
        model = self.default_model or DEFAULT_DEEPSEEK_MODEL
        for provider in self.providers:
            pid = provider.get("id") or ""
            if not is_chat_provider_id(pid):
                continue
            if model in (provider.get("model_ids") or []):
                return provider
        return by_id.get(DEEPSEEK_PROVIDER_ID) or dict(DEFAULT_DEEPSEEK_PROVIDER)

    def llm_from_stored(self) -> tuple[str, str, str, str]:
        """Return ``(api_key, base_url, model, api_style)`` from stored settings only (no env)."""
        model = self.default_model or DEFAULT_DEEPSEEK_MODEL
        provider = self.resolve_chat_provider_row()
        pid = provider.get("id") or DEEPSEEK_PROVIDER_ID
        api_style = normalize_api_style(provider.get("api_style"), pid)
        base_url = (provider.get("base_url") or "").strip() or default_base_url_for(pid, api_style)
        api_key = self.keys.get(pid) or ""
        return api_key or "", base_url, model, api_style

    def active_chat_provider_id(self) -> str:
        return self.resolve_chat_provider_row().get("id") or DEEPSEEK_PROVIDER_ID

    def has_keys(self) -> dict[str, bool]:
        """Stored keys. TypeSafe also counts ``TYPESAFE_API_KEY`` so the panel can default judgment."""
        flags = {
            DEEPSEEK_PROVIDER_ID: bool(self.deepseek_key),
            TYPESAFE_PROVIDER_ID: bool(resolve_typesafe_key(self.typesafe_key)),
        }
        for key, value in self.keys.items():
            if key not in flags:
                flags[key] = bool(value)
        return flags

    def masked_keys(self) -> dict[str, str | None]:
        return {key: mask_key(value) for key, value in self.keys.items()}


def parse_settings_row(
    default_model: str | None,
    providers_json: Any,
    api_keys_json: Any,
    chat_provider: str | None = None,
) -> StoredAgentCredentials:
    if isinstance(providers_json, str):
        providers = json.loads(providers_json or "[]")
    else:
        providers = list(providers_json or [])
    if isinstance(api_keys_json, str):
        keys = json.loads(api_keys_json or "{}")
    else:
        keys = dict(api_keys_json or {})
    cleaned = {k: v for k, v in keys.items() if isinstance(k, str) and v}
    chat = (chat_provider or DEEPSEEK_PROVIDER_ID).strip() or DEEPSEEK_PROVIDER_ID
    if not is_chat_provider_id(chat):
        chat = DEEPSEEK_PROVIDER_ID
    return StoredAgentCredentials(
        default_model=default_model or DEFAULT_DEEPSEEK_MODEL,
        providers=ensure_default_providers(providers),
        keys=cleaned,
        chat_provider=chat,
    )


def empty_credentials() -> StoredAgentCredentials:
    return parse_settings_row(
        DEFAULT_DEEPSEEK_MODEL,
        list(DEFAULT_AGENT_PROVIDERS),
        {},
        DEEPSEEK_PROVIDER_ID,
    )


def load_stored_credentials(db_path: str | None = None) -> StoredAgentCredentials:
    """Sync read of the singleton ``agent_settings`` row (for scripts / workers)."""
    path = os.path.expanduser(db_path or os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))
    if not os.path.exists(path):
        return empty_credentials()
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_settings)").fetchall()}
        select = "SELECT default_model, providers_json, api_keys_json"
        if "chat_provider" in cols:
            select += ", chat_provider"
        row = conn.execute(f"{select} FROM agent_settings WHERE id = 1").fetchone()
        conn.close()
    except sqlite3.Error:
        return empty_credentials()
    if row is None:
        return empty_credentials()
    chat = row["chat_provider"] if "chat_provider" in row.keys() else DEEPSEEK_PROVIDER_ID
    return parse_settings_row(row["default_model"], row["providers_json"], row["api_keys_json"], chat)
