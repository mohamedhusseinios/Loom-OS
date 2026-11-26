"""Optional at-rest encryption for provider API keys in state.db.

When ``LOOM_CREDENTIALS_KEY`` (or, as fallback, ``LOOM_AUTH_TOKEN``) is set,
``api_keys_json`` is stored as ``enc:v1:<base64>`` using Fernet. Without a key,
values stay plaintext but the DB file is still chmod'd 0600 by the registry.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

_PREFIX = "enc:v1:"


def credentials_key() -> Optional[str]:
    return os.environ.get("LOOM_CREDENTIALS_KEY") or os.environ.get("LOOM_AUTH_TOKEN") or None


def _fernet(key_material: str):
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_keys_json(plain_json: str) -> str:
    """Encrypt JSON text when a credentials key is available; else return plain."""
    material = credentials_key()
    if not material:
        return plain_json
    f = _fernet(material)
    if f is None:
        raise RuntimeError(
            "LOOM_CREDENTIALS_KEY/LOOM_AUTH_TOKEN is set but cryptography is not installed; "
            "pip install 'loom-os[crypto]' (or cryptography)"
        )
    token = f.encrypt(plain_json.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_api_keys_json(stored: str) -> str:
    """Decrypt ``enc:v1:…`` blobs; pass through plaintext JSON unchanged."""
    if not stored.startswith(_PREFIX):
        return stored
    material = credentials_key()
    if not material:
        raise ValueError("encrypted api_keys_json present but LOOM_CREDENTIALS_KEY/LOOM_AUTH_TOKEN unset")
    f = _fernet(material)
    if f is None:
        raise ValueError("encrypted api_keys_json present but cryptography package not installed")
    raw = f.decrypt(stored[len(_PREFIX):].encode("ascii"))
    return raw.decode("utf-8")
