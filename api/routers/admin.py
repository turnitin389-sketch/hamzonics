"""Admin portal API: search API keys (add / disable / reset / delete) and usage numbers.

Login with ADMIN_PASSWORD (empty = admin portal disabled). The session is an httpOnly,
SameSite=Strict cookie holding an HMAC-signed expiry; every request must also send the
header X-Requested-With: hamzonics (a cross-site form cannot), and failed logins are limited
per IP address.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.config import get_settings
from api.deps import DB, IpHash
from api.models import ApiKey, SearchCache, Status, Submission, utcnow
from api.secrets import decrypt, encrypt

router = APIRouter(prefix="/api/admin", tags=["admin"])
COOKIE = "hz_admin"
SESSION_S = 12 * 3600
_failures: dict[str, list[float]] = {}
MAX_FAILURES, FAILURE_WINDOW_S = 5, 15 * 60


def _sign(expiry: int) -> str:
    key = ("admin-session:" + get_settings().secret_key + get_settings().admin_password).encode()
    return f"{expiry}.{hmac.new(key, str(expiry).encode(), hashlib.sha256).hexdigest()}"


def require_admin(
    hz_admin: Annotated[str | None, Cookie()] = None,
    x_requested_with: Annotated[str | None, Header()] = None,
) -> None:
    if not get_settings().admin_password:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admin portal is disabled (set ADMIN_PASSWORD)")
    if x_requested_with != "hamzonics":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing request header")
    try:
        expiry = int((hz_admin or "").split(".", 1)[0])
    except ValueError:
        expiry = 0
    if not hz_admin or expiry < time.time() or not hmac.compare_digest(hz_admin, _sign(expiry)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in")


Admin = Depends(require_admin)


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


@router.post("/login")
def login(body: LoginIn, response: Response, ip: IpHash,
          x_requested_with: Annotated[str | None, Header()] = None) -> dict:
    s = get_settings()
    if not s.admin_password:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admin portal is disabled (set ADMIN_PASSWORD)")
    if x_requested_with != "hamzonics":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing request header")
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW_S]
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong passwords. Try again in 15 minutes.")
    if not hmac.compare_digest(body.password.encode(), s.admin_password.encode()):
        _failures[ip] = recent + [now]
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    _failures.pop(ip, None)
    response.set_cookie(COOKIE, _sign(int(now) + SESSION_S), max_age=SESSION_S, httponly=True, samesite="strict",
                        secure=s.public_base_url.startswith("https://"), path="/api/admin")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/api/admin")
    return {"ok": True}


class KeyOut(BaseModel):
    id: str
    provider: str
    label: str
    masked: str
    position: int
    active: bool
    status: str  # in use | waiting | used up | disabled | cannot decrypt
    exhausted_at: str | None
    last_error: str | None
    searches_used: int
    last_used_at: str | None
    created_at: str


def _out(rows: list[ApiKey]) -> list[KeyOut]:
    out: list[KeyOut] = []
    first_usable = True
    for r in rows:
        readable = decrypt(r.key_encrypted) is not None
        if not readable:
            state = "cannot decrypt"
        elif not r.active:
            state = "disabled"
        elif r.exhausted_at is not None:
            state = "used up"
        elif first_usable:
            state, first_usable = "in use", False
        else:
            state = "waiting"
        out.append(KeyOut(
            id=r.id, provider=r.provider, label=r.label, masked=f"••••••••{r.key_last4}", position=r.position,
            active=r.active, status=state, exhausted_at=r.exhausted_at.isoformat() if r.exhausted_at else None,
            last_error=r.last_error, searches_used=r.searches_used,
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None, created_at=r.created_at.isoformat(),
        ))
    return out


def _rows(db: DB) -> list[ApiKey]:
    return list(db.scalars(select(ApiKey).order_by(ApiKey.provider, ApiKey.position, ApiKey.created_at)).all())


@router.get("/keys", response_model=list[KeyOut], dependencies=[Admin])
def list_keys(db: DB) -> list[KeyOut]:
    return _out(_rows(db))


class KeysIn(BaseModel):
    keys: str = Field(max_length=20000, description="One or more keys, one per line (or separated by spaces/commas)")
    label: str = Field(default="", max_length=100)
    provider: str = Field(default="serper", pattern="^(serper)$")


@router.post("/keys", response_model=list[KeyOut], dependencies=[Admin])
def add_keys(body: KeysIn, db: DB) -> list[KeyOut]:
    candidates = [k for k in re.split(r"[\s,;]+", body.keys.strip()) if k]
    if not candidates:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Paste at least one key")
    bad = [k for k in candidates if not re.fullmatch(r"[A-Za-z0-9_\-]{16,200}", k)]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{len(bad)} value(s) do not look like API keys")
    existing = {decrypt(r.key_encrypted) for r in _rows(db) if r.provider == body.provider}
    position = (db.scalar(select(func.max(ApiKey.position)).where(ApiKey.provider == body.provider)) or 0)
    for k in dict.fromkeys(candidates):  # keep order, drop duplicates
        if k in existing:
            continue
        position += 1
        db.add(ApiKey(provider=body.provider, label=body.label or f"Key {position}", key_encrypted=encrypt(k),
                      key_last4=k[-4:], position=position, active=True, searches_used=0))
    db.commit()
    return _out(_rows(db))


class KeyPatch(BaseModel):
    active: bool | None = None
    reset: bool = False  # clear "used up" (e.g. after buying more credits)
    label: str | None = Field(default=None, max_length=100)
    move: str | None = Field(default=None, pattern="^(up|down)$")


@router.patch("/keys/{key_id}", response_model=list[KeyOut], dependencies=[Admin])
def update_key(key_id: str, body: KeyPatch, db: DB) -> list[KeyOut]:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    if body.active is not None:
        row.active = body.active
    if body.reset:
        row.exhausted_at, row.last_error = None, None
    if body.label is not None:
        row.label = body.label
    if body.move:
        rows = [r for r in _rows(db) if r.provider == row.provider]
        i = rows.index(row)
        j = i - 1 if body.move == "up" else i + 1
        if 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
            for pos, r in enumerate(rows, start=1):
                r.position = pos
    db.commit()
    return _out(_rows(db))


@router.delete("/keys/{key_id}", response_model=list[KeyOut], dependencies=[Admin])
def delete_key(key_id: str, db: DB) -> list[KeyOut]:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    db.delete(row)
    db.commit()
    return _out(_rows(db))


@router.get("/stats", dependencies=[Admin])
def stats(db: DB) -> dict:
    day = utcnow() - timedelta(days=1)
    by_status = dict(db.execute(select(Submission.status, func.count()).group_by(Submission.status)).all())
    usable = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.active.is_(True), ApiKey.exhausted_at.is_(None))) or 0
    return {
        "checks_total": sum(by_status.values()),
        "checks_last_24h": db.scalar(select(func.count()).select_from(Submission).where(Submission.created_at >= day)) or 0,
        "running": by_status.get(Status.RUNNING, 0),
        "queued": by_status.get(Status.QUEUED, 0),
        "failed": by_status.get(Status.FAILED, 0),
        "searches_used_total": db.scalar(select(func.coalesce(func.sum(ApiKey.searches_used), 0))) or 0,
        "searches_cached": db.scalar(select(func.count()).select_from(SearchCache)) or 0,
        "usable_keys": usable,
        "env_key_configured": bool(get_settings().serper_api_key),
    }
