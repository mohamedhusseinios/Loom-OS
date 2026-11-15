"""resolve_decision_config, threshold validation, and decision-client factory cache."""

import logging
from types import SimpleNamespace

import pytest

from daemon.decision import (
    DecisionConfig,
    GLiClassClient,
    NullDecisionClient,
    Thresholds,
    build_decision_clients,
    clear_decision_client_cache,
    effective_thresholds,
    resolve_decision_config,
)
from daemon.jev_client import JevClient


def _settings(**kwargs):
    base = {
        "filter_provider": None,
        "judgment_provider": None,
        "threshold_overrides": None,
        "providers": [],
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _ollama_provider(model: str = "nimble", base_url: str = "") -> dict:
    return {"id": "ollama", "base_url": base_url, "model_ids": [model] if model else []}


@pytest.fixture(autouse=True)
def _isolated_decision_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    clear_decision_client_cache()


def test_no_key_defaults_filter_and_judgment_to_none():
    config = resolve_decision_config(_settings(), {})
    assert config.filter_provider == "none"
    assert config.judgment_provider == "none"


def test_typesafe_key_defaults_both_roles_to_typesafe():
    config = resolve_decision_config(_settings(), {"typesafe": "ts-key"})
    assert config.filter_provider == "typesafe"
    assert config.judgment_provider == "typesafe"
    assert config.filter_api_key == "ts-key"
    assert config.judgment_api_key == "ts-key"
    assert config.filter_model == "jev-latest"


def test_env_typesafe_key_defaults_both_roles(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-env")
    config = resolve_decision_config(_settings(), {})
    assert config.filter_provider == "typesafe"
    assert config.judgment_provider == "typesafe"
    assert config.filter_api_key == "from-env"


def test_settings_key_beats_env_typesafe_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-env")
    config = resolve_decision_config(
        _settings(filter_provider="typesafe", judgment_provider="typesafe"),
        {"typesafe": "from-settings"},
    )
    assert config.filter_api_key == "from-settings"


def test_explicit_none_stays_none_when_typesafe_key_present():
    config = resolve_decision_config(
        _settings(filter_provider="none", judgment_provider="none"),
        {"typesafe": "ts-key"},
    )
    assert config.filter_provider == "none"
    assert config.judgment_provider == "none"
    relevance, judgment = build_decision_clients(config)
    assert isinstance(relevance, NullDecisionClient)
    assert relevance is judgment


def test_gliclass_judgment_falls_back_with_warning(caplog):
    settings = _settings(
        filter_provider="gliclass",
        judgment_provider="gliclass",
        providers=[{
            "id": "gliclass",
            "base_url": "http://127.0.0.1:8090",
            "model_ids": ["gliclass-edge"],
        }],
    )
    with caplog.at_level(logging.WARNING, logger="loom.decision"):
        config = resolve_decision_config(settings, {})
    assert config.filter_provider == "gliclass"
    assert config.judgment_provider == "none"
    assert "gliclass" in caplog.text.lower()
    assert "fall" in caplog.text.lower()


def test_gliclass_judgment_falls_back_to_typesafe_when_key_present(caplog):
    settings = _settings(filter_provider="gliclass", judgment_provider="gliclass")
    with caplog.at_level(logging.WARNING, logger="loom.decision"):
        config = resolve_decision_config(settings, {"typesafe": "ts-key"})
    assert config.filter_provider == "gliclass"
    assert config.judgment_provider == "typesafe"
    assert config.judgment_api_key == "ts-key"
    assert "gliclass" in caplog.text.lower()


def test_invalid_threshold_override_uses_defaults(caplog):
    settings = _settings(
        filter_provider="typesafe",
        judgment_provider="none",
        threshold_overrides={"typesafe": {"drop": 0.8, "mid": 0.2, "keep": 0.9}},
    )
    with caplog.at_level(logging.WARNING, logger="loom.decision"):
        config = resolve_decision_config(settings, {"typesafe": "ts-key"})
    assert config.filter_thresholds.as_dict() == effective_thresholds("typesafe")
    assert config.filter_thresholds.as_dict() == {
        "drop": 0.3, "mid": 0.5, "keep": 0.7, "escalate": 0.7,
    }
    assert "default" in caplog.text.lower()


def test_valid_threshold_override_applied():
    overrides = {"drop": 0.2, "mid": 0.5, "keep": 0.8}
    settings = _settings(
        filter_provider="ollama",
        judgment_provider="none",
        providers=[_ollama_provider()],
        threshold_overrides={"ollama": overrides},
    )
    config = resolve_decision_config(settings, {})
    resolved = config.filter_thresholds.as_dict()
    assert resolved["drop"] == 0.2
    assert resolved["mid"] == 0.5
    assert resolved["keep"] == 0.8
    assert resolved["escalate"] == 0.8
    assert resolved == effective_thresholds("ollama", overrides)


def test_ollama_requires_model_at_resolve():
    settings = _settings(
        filter_provider="ollama",
        judgment_provider="none",
        providers=[_ollama_provider(model="")],
    )
    with pytest.raises(ValueError, match="model"):
        resolve_decision_config(settings, {})


def test_ollama_defaults_base_url_and_allows_missing_key():
    config = resolve_decision_config(
        _settings(filter_provider="ollama", judgment_provider="ollama", providers=[_ollama_provider()]),
        {},
    )
    assert config.filter_model == "nimble"
    assert config.filter_base_url == "http://localhost:11434"
    assert config.filter_api_key == ""
    assert config.judgment_base_url == "http://localhost:11434"
    relevance, judgment = build_decision_clients(config)
    assert isinstance(relevance, JevClient)
    assert relevance is judgment
    assert relevance.provider == "ollama"
    assert relevance.available is True
    assert relevance.timeout == 5.0
    assert "11434" in relevance.base_url


def test_gliclass_filter_builds_http_client():
    config = resolve_decision_config(
        _settings(
            filter_provider="gliclass",
            judgment_provider="none",
            providers=[{
                "id": "gliclass",
                "base_url": "http://127.0.0.1:8090",
                "model_ids": ["gliclass-edge"],
            }],
        ),
        {"gliclass": "gli-from-settings"},
    )
    relevance, judgment = build_decision_clients(config)
    assert isinstance(relevance, GLiClassClient)
    assert relevance.__class__.__module__ == "daemon.gliclass_client"
    assert relevance.base_url == "http://127.0.0.1:8090"
    assert relevance.model == "gliclass-edge"
    assert relevance.api_key == "gli-from-settings"
    assert relevance.timeout == 5.0
    assert config.filter_api_key == "gli-from-settings"
    assert isinstance(judgment, NullDecisionClient)
    assert relevance is not judgment


def test_same_provider_config_reuses_one_client_and_cache():
    settings = _settings(filter_provider="typesafe", judgment_provider="typesafe")
    config = resolve_decision_config(settings, {"typesafe": "ts-key"})
    first_rel, first_jud = build_decision_clients(config)
    second_rel, second_jud = build_decision_clients(config)
    assert isinstance(first_rel, JevClient)
    assert first_rel is first_jud
    assert first_rel is second_rel
    assert first_jud is second_jud


def test_factory_does_not_share_clients_when_model_differs():
    thresholds = Thresholds(drop=0.3, mid=0.5, keep=0.7, escalate=0.7)
    config = DecisionConfig(
        filter_provider="typesafe",
        judgment_provider="typesafe",
        filter_model="jev-latest",
        judgment_model="jev-other",
        filter_base_url="https://api.typesafe.ai",
        judgment_base_url="https://api.typesafe.ai",
        filter_api_key="ts-key",
        judgment_api_key="ts-key",
        filter_thresholds=thresholds,
        judgment_thresholds=thresholds,
    )
    relevance, judgment = build_decision_clients(config)
    assert relevance is not judgment


def test_config_hash_changes_when_model_url_key_or_thresholds_change():
    base_settings = _settings(
        filter_provider="ollama",
        judgment_provider="none",
        providers=[_ollama_provider(base_url="http://localhost:11434")],
    )
    base = resolve_decision_config(base_settings, {}).cache_hash
    changed_model = resolve_decision_config(
        _settings(
            filter_provider="ollama",
            judgment_provider="none",
            providers=[_ollama_provider(model="other", base_url="http://localhost:11434")],
        ),
        {},
    ).cache_hash
    changed_url = resolve_decision_config(
        _settings(
            filter_provider="ollama",
            judgment_provider="none",
            providers=[_ollama_provider(base_url="http://127.0.0.1:11434")],
        ),
        {},
    ).cache_hash
    changed_key = resolve_decision_config(base_settings, {"ollama": "local-key"}).cache_hash
    changed_thresholds = resolve_decision_config(
        _settings(
            filter_provider="ollama",
            judgment_provider="none",
            providers=[_ollama_provider(base_url="http://localhost:11434")],
            threshold_overrides={"ollama": {"drop": 0.1, "mid": 0.4, "keep": 0.9}},
        ),
        {},
    ).cache_hash
    assert len({base, changed_model, changed_url, changed_key, changed_thresholds}) == 5


def test_changed_config_hash_builds_a_new_client():
    settings = _settings(filter_provider="typesafe", judgment_provider="none")
    first = resolve_decision_config(settings, {"typesafe": "key-a"})
    second = resolve_decision_config(settings, {"typesafe": "key-b"})
    assert first.cache_hash != second.cache_hash
    assert build_decision_clients(first)[0] is not build_decision_clients(second)[0]


def test_typesafe_base_url_uses_settings_then_env(monkeypatch):
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://typesafe.internal")
    from_env = resolve_decision_config(
        _settings(filter_provider="typesafe", judgment_provider="none"),
        {"typesafe": "ts-key"},
    )
    assert from_env.filter_base_url == "http://typesafe.internal"
    from_settings = resolve_decision_config(
        _settings(
            filter_provider="typesafe",
            judgment_provider="none",
            providers=[{"id": "typesafe", "base_url": "https://jev.example", "model_ids": ["jev-latest"]}],
        ),
        {"typesafe": "ts-key"},
    )
    assert from_settings.filter_base_url == "https://jev.example"
    assert from_env.cache_hash != from_settings.cache_hash
