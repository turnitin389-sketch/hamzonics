"""Request dependencies: database session, caller IP hash."""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_db

DB = Annotated[Session, Depends(get_db)]


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
        if forwarded.strip():
            return forwarded.strip()
    return request.client.host if request.client else "unknown"


def ip_hash(request: Request) -> str:
    """Keyed hash of the caller's IP: enough to rate-limit, useless to identify anyone."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, client_ip(request).encode(), hashlib.sha256).hexdigest()


IpHash = Annotated[str, Depends(ip_hash)]
