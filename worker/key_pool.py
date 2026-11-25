"""Search API keys: use them one after another, switch automatically when one runs out.

Keys come from the admin portal (table api_keys, in `position` order) plus, last, the key
in the environment (SERPER_API_KEY) if it is not already in the table. When the API says a
key has no credits left or is invalid, the key is marked exhausted and the next one is used
for the same search. Exhausted keys can be reset in the admin portal (e.g. after a top-up).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import select, update

from api.db import get_sessionmaker
from api.models import ApiKey, utcnow
from api.secrets import decrypt

log = logging.getLogger("hamzonics.keys")


@dataclass
class PoolKey:
    id: str | None  # None = the key from the environment
    secret: str


class KeyPool:
    def __init__(self, provider: str, env_key: str = "") -> None:
        self.provider = provider
        self._lock = threading.Lock()
        self._keys: list[PoolKey] = []
        with get_sessionmaker()() as db:
            rows = db.scalars(
                select(ApiKey).where(ApiKey.provider == provider, ApiKey.active.is_(True), ApiKey.exhausted_at.is_(None))
                .order_by(ApiKey.position, ApiKey.created_at)
            ).all()
            for row in rows:
                secret = decrypt(row.key_encrypted)
                if secret:
                    self._keys.append(PoolKey(row.id, secret))
        if env_key and all(k.secret != env_key for k in self._keys):
            self._keys.append(PoolKey(None, env_key))
        self._used: dict[str | None, int] = {}

    def __bool__(self) -> bool:
        return bool(self._keys)

    def current(self) -> PoolKey | None:
        with self._lock:
            return self._keys[0] if self._keys else None

    def record_use(self, key: PoolKey) -> None:
        with self._lock:
            self._used[key.id] = self._used.get(key.id, 0) + 1

    def exhausted(self, key: PoolKey, reason: str) -> None:
        """Take this key out of rotation (no credits left / rejected) and remember why."""
        with self._lock:
            if key in self._keys:
                self._keys.remove(key)
            remaining = len(self._keys)
        log.warning("%s key ...%s stopped: %s (%d key(s) left)", self.provider, key.secret[-4:], reason, remaining)
        if key.id is not None:
            with get_sessionmaker()() as db:
                db.execute(update(ApiKey).where(ApiKey.id == key.id).values(
                    exhausted_at=utcnow(), last_error=reason[:300]))
                db.commit()

    def flush_usage(self) -> None:
        """Add this check's searches to each key's counter (one write per key per check)."""
        with self._lock:
            used, self._used = self._used, {}
        rows = {k: n for k, n in used.items() if k is not None and n}
        if not rows:
            return
        with get_sessionmaker()() as db:
            for key_id, n in rows.items():
                db.execute(update(ApiKey).where(ApiKey.id == key_id).values(
                    searches_used=ApiKey.searches_used + n, last_used_at=utcnow()))
            db.commit()
