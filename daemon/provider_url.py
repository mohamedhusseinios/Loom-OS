"""Outbound URL policy for listing provider models.

Stored and environment API keys are sent only to the provider URL already
saved in settings (or the official default for a built-in preset). A request
``base_url`` that does not match must bring its own API key. That URL has to
be https on a public host, or http on loopback. Error text never includes the
caller-supplied URL.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from typing import NoReturn
from urllib.parse import unquote, urlsplit, urlunsplit

from daemon.agent_credentials import (
    ANTHROPIC_PROVIDER_ID,
    DEEPSEEK_PROVIDER_ID,
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
    OPENAI_PROVIDER_ID,
)

_MAX_URL_LENGTH = 2048
_METADATA_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.google.com",
    "metadata",
    "instance-data",
})
_UNTRUSTED_BLOCKED_SUFFIXES = (".local", ".localhost", ".localdomain", ".internal", ".intranet")
_PRESET_DEFAULTS = {
    DEEPSEEK_PROVIDER_ID: DEFAULT_DEEPSEEK_BASE_URL,
    OPENAI_PROVIDER_ID: DEFAULT_OPENAI_BASE_URL,
    ANTHROPIC_PROVIDER_ID: DEFAULT_ANTHROPIC_BASE_URL,
}


class ProviderUrlError(ValueError):
    """Raised when a provider base URL must not be contacted."""


def _official_hosts() -> frozenset[str]:
    hosts: set[str] = set()
    for url in _PRESET_DEFAULTS.values():
        host = urlsplit(url).hostname
        if host:
            hosts.add(host.lower().rstrip("."))
    return frozenset(hosts)


OFFICIAL_HTTPS_HOSTS = _official_hosts()
_RESOLVE_LOCK = threading.Lock()


def _fail(message: str = "base_url is not allowed") -> NoReturn:
    raise ProviderUrlError(message)


def normalize_base_url(url: str) -> str:
    """Return a canonical http(s) base URL, or raise ``ProviderUrlError``."""
    raw = (url or "").strip()
    if not raw or len(raw) > _MAX_URL_LENGTH:
        _fail()
    if any(ord(ch) < 32 or ch in " \t\\" for ch in raw):
        _fail()
    decoded = unquote(raw)
    if any(ord(ch) < 32 or ch.isspace() or ch in "@\\" for ch in decoded):
        _fail()
    parts = urlsplit(decoded)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or parts.username or parts.password or parts.query or parts.fragment:
        _fail()
    try:
        port = parts.port
    except ValueError:
        _fail()
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "%" in host or ".." in host:
        _fail()
    ip = _parse_ip(host)
    if ip is not None:
        ip = _canonical_ip(ip)
        host_text = ip.compressed
        if isinstance(ip, ipaddress.IPv6Address):
            host_text = f"[{host_text}]"
    else:
        if any(label == "" for label in host.split(".")):
            _fail()
        try:
            host_text = host.encode("idna").decode("ascii")
        except UnicodeError:
            _fail()
    if scheme == "http" and port == 80:
        port = None
    if scheme == "https" and port == 443:
        port = None
    netloc = f"{host_text}:{port}" if port else host_text
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def base_urls_match(left: str, right: str) -> bool:
    try:
        return normalize_base_url(left) == normalize_base_url(right)
    except ProviderUrlError:
        return False


def _trusted_saved_url(provider_id: str, saved_base_url: str) -> str:
    saved = (saved_base_url or "").strip()
    if saved:
        try:
            return normalize_base_url(saved)
        except ProviderUrlError:
            return ""
    default = _PRESET_DEFAULTS.get(provider_id, "")
    return normalize_base_url(default) if default else ""


def resolve_list_models_target(provider_id: str, saved_base_url: str, requested_base_url: str, has_draft_key: bool) -> tuple[str, bool]:
    """Return ``(base_url, allow_stored_key)`` for a list-models request.

    ``allow_stored_key`` is true only when the destination is the saved
    provider URL (or the official preset default when nothing is saved).
    """
    requested = (requested_base_url or "").strip()
    trusted = _trusted_saved_url(provider_id, saved_base_url)
    if trusted and (not requested or base_urls_match(requested, trusted)):
        return assert_saved_base_url(trusted), True
    if not requested:
        _fail("base_url is required")
    if not has_draft_key:
        _fail("API key is required for a base URL that is not the saved provider URL")
    return assert_untrusted_base_url(requested), False


def assert_saved_base_url(url: str) -> str:
    """Normalize a URL that may receive a stored key."""
    normalized = normalize_base_url(url)
    host = urlsplit(normalized).hostname or ""
    _reject_metadata_name(host)
    ip = _parse_ip(host)
    if ip is not None and _is_dangerous_ip(ip):
        _fail()
    return normalized


def assert_untrusted_base_url(url: str) -> str:
    """Normalize a caller-supplied URL that must not receive a stored key."""
    normalized = normalize_base_url(url)
    parts = urlsplit(normalized)
    host = parts.hostname or ""
    _reject_metadata_name(host)
    if any(host.endswith(suffix) for suffix in _UNTRUSTED_BLOCKED_SUFFIXES):
        _fail()
    ip = _parse_ip(host)
    if parts.scheme == "http":
        if host != "localhost" and (ip is None or not _canonical_ip(ip).is_loopback):
            _fail()
        return normalized
    if host in OFFICIAL_HTTPS_HOSTS:
        return normalized
    if ip is not None or not _resolves_public(host, parts.port or 443):
        _fail()
    return normalized


def _reject_metadata_name(host: str) -> None:
    if host in _METADATA_HOSTS:
        _fail()


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _canonical_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped or ip


def _is_dangerous_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = _canonical_ip(ip)
    if ip.is_loopback:
        return False
    return ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = _canonical_ip(ip)
    if ip.is_multicast or ip.is_reserved or ip.is_link_local or ip.is_unspecified or ip.is_loopback or ip.is_private:
        return False
    return bool(ip.is_global)


def _resolve_ips(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    with _RESOLVE_LOCK:
        previous = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(3.0)
            try:
                infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except (socket.gaierror, socket.timeout, UnicodeError, OSError):
                _fail()
        finally:
            socket.setdefaulttimeout(previous)
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else ()
        if not sockaddr:
            _fail()
        try:
            found.append(_canonical_ip(ipaddress.ip_address(sockaddr[0].split("%", 1)[0])))
        except ValueError:
            _fail()
    if not found:
        _fail()
    return found


def _resolves_public(host: str, port: int) -> bool:
    return all(_is_public_ip(ip) for ip in _resolve_ips(host, port))
