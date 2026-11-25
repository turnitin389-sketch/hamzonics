"""Database engine and session handling (PostgreSQL in production, SQLite for local dev/tests)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from api.config import get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    """(Re)create the global engine. Tests call this with a temporary database URL."""
    global _engine, _sessionmaker
    url = url or get_settings().database_url
    if _engine is not None:
        _engine.dispose()
    if url.startswith("sqlite"):
        _engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            # Many checks at once: wait for the write lock instead of failing.
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
    else:
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    _sessionmaker = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
