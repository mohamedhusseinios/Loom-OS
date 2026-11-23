"""URL policy for list-models: stored keys stay on the saved host."""
import ipaddress

import pytest

from daemon.provider_url import (
    ProviderUrlError,
    assert_saved_base_url,
    assert_untrusted_base_url,
    base_urls_match,
    normalize_base_url,
    resolve_list_models_target,
)


def test_normalize_canonicalizes_case_port_and_slash():
    assert normalize_base_url("https://API.DeepSeek.com:443/") == "https://api.deepseek.com"
    assert normalize_base_url("http://[0:0:0:0:0:0:0:1]:11434/") == "http://[::1]:11434"
    assert base_urls_match("https://api.deepseek.com/", "https://API.DeepSeek.com")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://127.0.0.1",
    "https://user:sk-secret@api.deepseek.com",
    "https://api.deepseek.com@evil.com",
    "https://evil.com%00.example",
    "https://api.deepseek.com/v1?x=1",
    "https://api.deepseek.com/v1#frag",
    "http://169.254.169.254",
    "http://[::ffff:169.254.169.254]",
    "http://0.0.0.0",
    "http://224.0.0.1",
    "https://metadata.google.internal",
])
def test_saved_url_rejects_dangerous_targets(url):
    with pytest.raises(ProviderUrlError) as exc:
        assert_saved_base_url(url)
    assert "sk-secret" not in str(exc.value)
    assert "169.254.169.254" not in str(exc.value)
    assert str(exc.value) == "base_url is not allowed"


def test_saved_url_allows_loopback_and_lan():
    assert assert_saved_base_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert assert_saved_base_url("http://[::1]:11434") == "http://[::1]:11434"
    assert assert_saved_base_url("http://192.168.1.20:11434/") == "http://192.168.1.20:11434"
    assert assert_saved_base_url("https://api.deepseek.com") == "https://api.deepseek.com"


def test_untrusted_https_allows_official_and_public_names(monkeypatch):
    monkeypatch.setattr(
        "daemon.provider_url._resolve_ips",
        lambda host, port: [ipaddress.ip_address("93.184.216.34")],
    )
    assert assert_untrusted_base_url("https://api.openai.com/") == "https://api.openai.com"
    assert assert_untrusted_base_url("https://example.com/v1") == "https://example.com/v1"


def test_untrusted_rejects_private_resolution_and_ip_literals(monkeypatch):
    monkeypatch.setattr(
        "daemon.provider_url._resolve_ips",
        lambda host, port: [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("10.0.0.1")],
    )
    with pytest.raises(ProviderUrlError):
        assert_untrusted_base_url("https://example.com")
    for url in (
        "http://10.1.2.3",
        "http://169.254.169.254/latest/meta-data",
        "https://8.8.8.8",
        "https://example.local",
        "http://localhost.evil.com",
    ):
        with pytest.raises(ProviderUrlError):
            assert_untrusted_base_url(url)


def test_untrusted_http_allows_only_loopback():
    assert assert_untrusted_base_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert assert_untrusted_base_url("http://localhost:11434/") == "http://localhost:11434"
    assert assert_untrusted_base_url("http://[::1]:8080") == "http://[::1]:8080"


def test_stored_key_only_for_saved_or_preset_default():
    with pytest.raises(ProviderUrlError, match="API key is required"):
        resolve_list_models_target("deepseek", "https://api.deepseek.com", "https://attacker.example", False)

    url, allow = resolve_list_models_target(
        "deepseek", "https://api.deepseek.com", "https://API.DeepSeek.com/", False,
    )
    assert allow is True
    assert url == "https://api.deepseek.com"

    url, allow = resolve_list_models_target("openai", "", "", False)
    assert allow is True
    assert url == "https://api.openai.com"

    url, allow = resolve_list_models_target("custom-x", "", "https://api.anthropic.com", True)
    assert allow is False
    assert url == "https://api.anthropic.com"

    with pytest.raises(ProviderUrlError, match="base_url is required"):
        resolve_list_models_target("custom-x", "", "", True)
