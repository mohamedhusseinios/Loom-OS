"""Resolve Loom Agent API keys from dashboard settings with env fallback.

DeepSeek and TypeSafe (Jev) keys are stored in ``agent_settings.api_keys_json``
as plaintext — the existing DeepSeek BYOK path has no at-rest encryption.
GET endpoints must return only masked values plus ``has_keys`` booleans, never
the raw secret. Runtime reads settings on every cycle (no daemon restart).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

DEEPSEEK_PROVIDER_ID = "deepseek"
TYPESAFE_PROVIDER_ID = "typesafe"

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_TYPESAFE_BASE_URL = "https://api.typesafe.ai"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_PROVIDER_ID = "ollama"
GLICLASS_PROVIDER_ID = "gliclass"

BUILTIN_PROVIDER_IDS: frozenset[str] = frozenset({DEEPSEEK_PROVIDER_ID, TYPESAFE_PROVIDER_ID, OLLAMA_PROVIDER_ID, GLICLASS_PROVIDER_ID})
PROVIDER_KIND_BUILTIN = "builtin"
PROVIDER_KIND_OPENAI = "openai_compatible"

DEFAULT_DEEPSEEK_PROVIDER: dict[str, Any] = {
    "id": DEEPSEEK_PROVIDER_ID,
    "name": "DeepSeek",
    "base_url": DEFAULT_DEEPSEEK_BASE_URL,
    "model_ids": [DEFAULT_DEEPSEEK_MODEL],
}

DEFAULT_TYPESAFE_PROVIDER: dict[str, Any] = {
    "id": TYPESAFE_PROVIDER_ID,
    "name": "TypeSafe (Jev)",
    "base_url": "",
    "model_ids": ["jev-latest"],
}

DEFAULT_OLLAMA_PROVIDER: dict[str, Any] = {
    "id": OLLAMA_PROVIDER_ID,
    "name": "Ollama",
    "base_url": DEFAULT_OLLAMA_BASE_URL,
    "model_ids": [],
}

DEFAULT_GLICLASS_PROVIDER: dict[str, Any] = {
    "id": GLICLASS_PROVIDER_ID,
    "name": "GLiClass",
    "base_url": "",
    "model_ids": [],
}

DEFAULT_AGENT_PROVIDERS: tuple[dict[str, Any], ...] = (
    DEFAULT_DEEPSEEK_PROVIDER,
    DEFAULT_TYPESAFE_PROVIDER,
    DEFAULT_OLLAMA_PROVIDER,
    DEFAULT_GLICLASS_PROVIDER,
)


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


def _as_provider_dict(provider: Any) -> dict[str, Any]:
    if hasattr(provider, "model_dump"):
        return provider.model_dump()
    if isinstance(provider, dict):
        return dict(provider)
    raise TypeError(f"unsupported provider value: {type(provider)!r}")


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


def provider_base_url(providers: list[dict[str, Any]], provider_id: str, default: str = "") -> str:
    for provider in providers:
        if provider.get("id") == provider_id:
            return (provider.get("base_url") or "").strip() or default
    return default


def resolve_deepseek_key(settings_key: str | None) -> str:
    """Dashboard settings first, then ``DEEPSEEK_API_KEY`` (existing runtime order)."""
    return first_nonempty(settings_key, os.environ.get("DEEPSEEK_API_KEY", ""))


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

    @property
    def deepseek_key(self) -> str:
        return self.keys.get(DEEPSEEK_PROVIDER_ID, "") or ""

    @property
    def typesafe_key(self) -> str:
        return self.keys.get(TYPESAFE_PROVIDER_ID, "") or ""

    @property
    def typesafe_base_url(self) -> str:
        return provider_base_url(self.providers, TYPESAFE_PROVIDER_ID, "")

    def llm_from_stored(self) -> tuple[str, str, str]:
        """Return ``(api_key, base_url, model)`` from stored settings only (no env).

        The DeepSeek provider row is the BYOK chat endpoint: its ``base_url``
        always applies even when ``default_model`` is a custom id not listed in
        ``model_ids`` (the settings UI keeps ``model_ids`` as ``deepseek-chat``).
        """
        model = self.default_model or DEFAULT_DEEPSEEK_MODEL
        for provider in self.providers:
            pid = provider.get("id") or ""
            if model not in (provider.get("model_ids") or []):
                continue
            if pid == DEEPSEEK_PROVIDER_ID or normalize_provider_kind(provider)["kind"] == PROVIDER_KIND_OPENAI:
                base_url = (provider.get("base_url") or "").strip() or DEFAULT_DEEPSEEK_BASE_URL
                return self.keys.get(pid) or "", base_url, model
        base_url = DEFAULT_DEEPSEEK_BASE_URL
        for provider in self.providers:
            if provider.get("id") == DEEPSEEK_PROVIDER_ID:
                base_url = (provider.get("base_url") or "").strip() or base_url
        return self.deepseek_key or "", base_url, model

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
    return StoredAgentCredentials(
        default_model=default_model or DEFAULT_DEEPSEEK_MODEL,
        providers=ensure_default_providers(providers),
        keys=cleaned,
    )


def empty_credentials() -> StoredAgentCredentials:
    return parse_settings_row(
        DEFAULT_DEEPSEEK_MODEL,
        [DEFAULT_DEEPSEEK_PROVIDER, DEFAULT_TYPESAFE_PROVIDER],
        {},
    )


def load_stored_credentials(db_path: str | None = None) -> StoredAgentCredentials:
    """Sync read of the singleton ``agent_settings`` row (for scripts / workers)."""
    path = os.path.expanduser(db_path or os.environ.get("LOOM_DB_PATH", "~/.loom/state.db"))
    if not os.path.exists(path):
        return empty_credentials()
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT default_model, providers_json, api_keys_json "
            "FROM agent_settings WHERE id = 1"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return empty_credentials()
    if row is None:
        return empty_credentials()
    return parse_settings_row(row["default_model"], row["providers_json"], row["api_keys_json"])
