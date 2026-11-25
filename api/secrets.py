"""Encrypt API keys at rest (Fernet, key derived from SECRET_KEY).

Changing SECRET_KEY makes stored keys unreadable: they then show as "cannot decrypt" in the
admin portal and must be added again."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from api.config import get_settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(("api-keys:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
