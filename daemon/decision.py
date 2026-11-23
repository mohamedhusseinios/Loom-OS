"""Pluggable decision layer — normalized DecisionResult and client protocol.

``resolve_decision_config`` is the only settings read for filter/judgment roles.
``build_decision_clients`` caches clients by a hash of the full config.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from daemon.agent_credentials import BUILTIN_PROVIDER_IDS, DEFAULT_OLLAMA_BASE_URL, DEFAULT_OPENROUTER_JEV_BASE_URL, DEFAULT_OPENROUTER_JEV_MODEL, DEFAULT_TYPESAFE_BASE_URL, PROVIDER_KIND_OPENAI, normalize_provider_kind
from daemon.gliclass_client import GLiClassClient
from daemon.jev_client import DEFAULT_MODEL as DEFAULT_TYPESAFE_MODEL
from daemon.jev_client import JevClient

logger = logging.getLogger("loom.decision")

SkipReason = Literal["none", "error", "timeout", "bad_payload", "unsupported"]
ProviderId = Literal["typesafe", "openrouter_jev", "ollama", "gliclass", "none"]


@dataclass
class DecisionUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class DecisionResult:
    scores: dict[str, float] = field(default_factory=dict)
    usage: DecisionUsage = field(default_factory=DecisionUsage)
    provider: ProviderId = "none"
    model: str = ""
    skipped: bool = False
    skip_reason: SkipReason | None = None
    latency_ms: float = 0.0


def _null_result() -> DecisionResult:
    t0 = time.perf_counter()
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return DecisionResult(
        scores={},
        usage=DecisionUsage(input_tokens=None, output_tokens=None),
        provider="none",
        model="",
        skipped=True,
        skip_reason="none",
        latency_ms=latency_ms,
    )


@runtime_checkable
class DecisionClient(Protocol):
    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult: ...

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult: ...


class NullDecisionClient:
    """Judgment/filter no-op: always skipped with reason ``none`` (orchestrator escalates)."""

    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult:
        return _null_result()

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult:
        return _null_result()


# Jev band edges match orchestrator NOUL_NO / NOUL_YES. ``mid`` is the midpoint
# and must sit strictly between drop and keep. ``escalate`` follows keep unless
# an override sets it, so a winning score below escalate matches today's
# ``confidence < 0.7`` rule. GLiClass keep is 0.5 (usual serve threshold).
_DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "typesafe": {"drop": 0.3, "mid": 0.5, "keep": 0.7, "escalate": 0.7},
    "openrouter_jev": {"drop": 0.3, "mid": 0.5, "keep": 0.7, "escalate": 0.7},
    "ollama": {"drop": 0.3, "mid": 0.5, "keep": 0.7, "escalate": 0.7},
    "gliclass": {"drop": 0.2, "mid": 0.35, "keep": 0.5, "escalate": 0.5},
    "none": {"drop": 0.3, "mid": 0.5, "keep": 0.7, "escalate": 0.7},
}
_FILTER_PROVIDERS = frozenset({"typesafe", "openrouter_jev", "ollama", "gliclass", "none"})
_JUDGMENT_PROVIDERS = frozenset({"typesafe", "openrouter_jev", "ollama", "none"})


@dataclass(frozen=True)
class Thresholds:
    drop: float
    mid: float
    keep: float
    escalate: float

    def as_dict(self) -> dict[str, float]:
        return {"drop": self.drop, "mid": self.mid, "keep": self.keep, "escalate": self.escalate}


@dataclass(frozen=True)
class DecisionConfig:
    filter_provider: str
    judgment_provider: str
    filter_model: str
    judgment_model: str
    filter_base_url: str
    judgment_base_url: str
    filter_api_key: str
    judgment_api_key: str
    filter_thresholds: Thresholds
    judgment_thresholds: Thresholds

    @property
    def cache_hash(self) -> str:
        payload = {
            "filter_provider": self.filter_provider,
            "judgment_provider": self.judgment_provider,
            "filter_model": self.filter_model,
            "judgment_model": self.judgment_model,
            "filter_base_url": self.filter_base_url,
            "judgment_base_url": self.judgment_base_url,
            "filter_api_key": self.filter_api_key,
            "judgment_api_key": self.judgment_api_key,
            "filter_thresholds": self.filter_thresholds.as_dict(),
            "judgment_thresholds": self.judgment_thresholds.as_dict(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _default_thresholds(provider: str) -> dict[str, float]:
    return dict(_DEFAULT_THRESHOLDS.get(provider, _DEFAULT_THRESHOLDS["typesafe"]))


def _unit_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be a number in [0, 1]")
    number = float(value)
    if number < 0.0 or number > 1.0:
        raise ValueError("threshold must be a number in [0, 1]")
    return number


def effective_thresholds(provider: str, overrides: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Return drop/mid/keep/escalate for ``provider``.

    ``overrides`` is the optional per-provider map. Values must satisfy
    ``0 <= drop < mid < keep <= 1``; otherwise a warning is logged and code
    defaults are returned. Omitted ``escalate`` follows ``keep``.
    """
    defaults = _default_thresholds(provider)
    if not overrides:
        return defaults
    merged = dict(defaults)
    try:
        for key in ("drop", "mid", "keep"):
            if key in overrides:
                merged[key] = _unit_float(overrides[key])
        if "escalate" in overrides:
            merged["escalate"] = _unit_float(overrides["escalate"])
        else:
            merged["escalate"] = merged["keep"]
    except ValueError:
        logger.warning("invalid threshold override for provider %s; using defaults", provider)
        return defaults
    if not (0.0 <= merged["drop"] < merged["mid"] < merged["keep"] <= 1.0):
        logger.warning("invalid threshold override for provider %s; using defaults", provider)
        return defaults
    return merged


def _thresholds_from(values: Mapping[str, float]) -> Thresholds:
    return Thresholds(drop=float(values["drop"]), mid=float(values["mid"]), keep=float(values["keep"]), escalate=float(values["escalate"]))


def _get(settings: Any, name: str, default: Any = None) -> Any:
    if settings is None:
        return default
    if isinstance(settings, Mapping):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _norm_provider(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _as_provider_row(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {
        "id": getattr(item, "id", "") or "",
        "base_url": getattr(item, "base_url", "") or "",
        "model_ids": list(getattr(item, "model_ids", []) or []),
        "kind": getattr(item, "kind", "") or "",
    }


def _provider_rows(settings: Any) -> list[dict[str, Any]]:
    raw = _get(settings, "providers", []) or []
    return [_as_provider_row(item) for item in raw]


def _find_provider(rows: list[dict[str, Any]], provider_id: str) -> dict[str, Any]:
    for row in rows:
        if (row.get("id") or "") == provider_id:
            return row
    return {}


def _first_model(row: Mapping[str, Any], default: str) -> str:
    for model_id in row.get("model_ids") or []:
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip()
    return default


def _row_base_url(row: Mapping[str, Any]) -> str:
    return str(row.get("base_url") or "").strip().rstrip("/")


def _clean_keys(raw_keys: Mapping[str, str] | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    if not raw_keys:
        return cleaned
    for key, value in raw_keys.items():
        if isinstance(key, str) and value:
            cleaned[key] = str(value)
    return cleaned


def _provider_key(keys: Mapping[str, str], provider: str) -> str:
    found = str(keys.get(provider) or "")
    if provider == "typesafe" and not found:
        found = os.environ.get("TYPESAFE_API_KEY", "") or ""
    return found


def _typesafe_base_url(row: Mapping[str, Any]) -> str:
    configured = _row_base_url(row)
    if configured:
        return configured
    env_url = (os.environ.get("TYPESAFE_BASE_URL") or "").strip().rstrip("/")
    return env_url or DEFAULT_TYPESAFE_BASE_URL.rstrip("/")


def _threshold_overrides(settings: Any) -> dict[str, Any]:
    raw = _get(settings, "threshold_overrides", None)
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("invalid threshold_overrides JSON; using defaults")
            return {}
        raw = parsed
    if not isinstance(raw, Mapping):
        logger.warning("invalid threshold_overrides; using defaults")
        return {}
    return dict(raw)


def _overrides_for(all_overrides: Mapping[str, Any], provider: str) -> dict[str, Any] | None:
    if provider not in all_overrides:
        return None
    raw = all_overrides[provider]
    if isinstance(raw, Mapping):
        return dict(raw)
    logger.warning("invalid threshold override for provider %s; using defaults", provider)
    return None


def _is_custom_provider(provider_id: str, rows: list[dict[str, Any]]) -> bool:
    """True when ``provider_id`` is a non-builtin row whose kind is openai_compatible (kind inferred when missing)."""
    if provider_id in BUILTIN_PROVIDER_IDS:
        return False
    row = _find_provider(rows, provider_id)
    return bool(row) and normalize_provider_kind(row).get("kind") == PROVIDER_KIND_OPENAI


def _lazy_provider(has_typesafe_key: bool) -> str:
    return "typesafe" if has_typesafe_key else "none"


def _resolve_roles(settings: Any, keys: Mapping[str, str]) -> tuple[str, str]:
    filt = _norm_provider(_get(settings, "filter_provider", None))
    judg = _norm_provider(_get(settings, "judgment_provider", None))
    has_typesafe_key = bool(_provider_key(keys, "typesafe"))
    if filt is None:
        filt = _lazy_provider(has_typesafe_key)
    if judg is None:
        judg = _lazy_provider(has_typesafe_key)
    if judg == "gliclass":
        fallback = _lazy_provider(has_typesafe_key)
        logger.warning("judgment_provider=gliclass is rejected in Phase 1; falling back to %s", fallback)
        judg = fallback
    rows = _provider_rows(settings)
    if filt not in _FILTER_PROVIDERS and not _is_custom_provider(filt, rows):
        logger.warning("unknown filter_provider=%s; falling back to none", filt)
        filt = "none"
    if judg not in _JUDGMENT_PROVIDERS and not _is_custom_provider(judg, rows):
        logger.warning("unknown judgment_provider=%s; falling back to none", judg)
        judg = "none"
    return filt, judg


def _openrouter_jev_base_url(row: Mapping[str, Any]) -> str:
    configured = _row_base_url(row)
    if configured:
        return configured
    return DEFAULT_OPENROUTER_JEV_BASE_URL.rstrip("/")


def _role_endpoint(provider: str, rows: list[dict[str, Any]], keys: Mapping[str, str], overrides: Mapping[str, Any]) -> tuple[str, str, str, Thresholds]:
    row = _find_provider(rows, provider)
    thresholds = _thresholds_from(effective_thresholds(provider, _overrides_for(overrides, provider)))
    if provider == "ollama" or _is_custom_provider(provider, rows):
        model = _first_model(row, "")
        if not model:
            raise ValueError(f"{'Ollama' if provider == 'ollama' else provider} decision provider requires a model")
        base_url = _row_base_url(row) or (DEFAULT_OLLAMA_BASE_URL if provider == "ollama" else "")
        if not base_url:
            raise ValueError(f"{provider} decision provider requires a base_url")
        return model, base_url, _provider_key(keys, provider), thresholds
    if provider == "gliclass":
        return _first_model(row, ""), _row_base_url(row), _provider_key(keys, "gliclass"), thresholds
    if provider == "typesafe":
        model = _first_model(row, DEFAULT_TYPESAFE_MODEL)
        return model, _typesafe_base_url(row), _provider_key(keys, "typesafe"), thresholds
    if provider == "openrouter_jev":
        model = _first_model(row, DEFAULT_OPENROUTER_JEV_MODEL)
        return model, _openrouter_jev_base_url(row), _provider_key(keys, "openrouter_jev"), thresholds
    return "", "", "", thresholds


def resolve_decision_config(settings: Any, raw_keys: Mapping[str, str] | None = None) -> DecisionConfig:
    """Resolve filter and judgment roles, endpoints, keys, and effective thresholds."""
    keys = _clean_keys(raw_keys)
    rows = _provider_rows(settings)
    overrides = _threshold_overrides(settings)
    filter_provider, judgment_provider = _resolve_roles(settings, keys)
    filter_model, filter_base_url, filter_api_key, filter_thresholds = _role_endpoint(filter_provider, rows, keys, overrides)
    judgment_model, judgment_base_url, judgment_api_key, judgment_thresholds = _role_endpoint(judgment_provider, rows, keys, overrides)
    return DecisionConfig(
        filter_provider=filter_provider,
        judgment_provider=judgment_provider,
        filter_model=filter_model,
        judgment_model=judgment_model,
        filter_base_url=filter_base_url,
        judgment_base_url=judgment_base_url,
        filter_api_key=filter_api_key,
        judgment_api_key=judgment_api_key,
        filter_thresholds=filter_thresholds,
        judgment_thresholds=judgment_thresholds,
    )


_client_cache: dict[str, tuple[DecisionClient, DecisionClient]] = {}


def clear_decision_client_cache() -> None:
    _client_cache.clear()


def _same_endpoint(config: DecisionConfig) -> bool:
    return (
        config.filter_provider == config.judgment_provider
        and config.filter_model == config.judgment_model
        and config.filter_base_url == config.judgment_base_url
        and config.filter_api_key == config.judgment_api_key
    )


def _build_one(provider: str, model: str, base_url: str, api_key: str) -> DecisionClient:
    if provider == "gliclass":
        return GLiClassClient(base_url=base_url, model=model, api_key=api_key, timeout=5.0)
    if provider in ("typesafe", "openrouter_jev", "ollama"):
        timeout = 5.0 if provider == "ollama" else 10.0
        default_model = DEFAULT_OPENROUTER_JEV_MODEL if provider == "openrouter_jev" else DEFAULT_TYPESAFE_MODEL
        return JevClient(api_key=api_key, base_url=base_url or None, timeout=timeout, provider=provider, model=model or default_model)
    if provider not in BUILTIN_PROVIDER_IDS and provider != "none":
        # Custom openai_compatible id: JevClient only knows typesafe|ollama, so use the ollama (keyless-ok, 5s) path.
        return JevClient(api_key=api_key, base_url=base_url or None, timeout=5.0, provider="ollama", model=model)
    return NullDecisionClient()


def build_decision_clients(config: DecisionConfig) -> tuple[DecisionClient, DecisionClient]:
    """Return ``(relevance, judgment)``. Same endpoint shares one instance.

    The cache key is ``DecisionConfig.cache_hash`` (providers, models, URLs, keys, thresholds).
    """
    cached = _client_cache.get(config.cache_hash)
    if cached is not None:
        return cached
    relevance = _build_one(config.filter_provider, config.filter_model, config.filter_base_url, config.filter_api_key)
    if _same_endpoint(config):
        pair: tuple[DecisionClient, DecisionClient] = (relevance, relevance)
    else:
        judgment = _build_one(config.judgment_provider, config.judgment_model, config.judgment_base_url, config.judgment_api_key)
        pair = (relevance, judgment)
    _client_cache[config.cache_hash] = pair
    return pair