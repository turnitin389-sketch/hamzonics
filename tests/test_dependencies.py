"""Version combinations that only fail at runtime on the server (found in the Docker test)."""

from __future__ import annotations


def _v(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split(".")[:3] if p.isdigit())


def test_kombu_redis_transport_has_a_supported_redis_client() -> None:
    """kombu >= 5.6 refuses redis-py < 6.1 when the worker connects ("VersionMismatch"),
    so every check would stay queued forever."""
    import kombu
    import redis

    if _v(kombu.__version__) >= (5, 6):
        assert _v(redis.__version__) >= (6, 1), f"kombu {kombu.__version__} needs redis-py >= 6.1, have {redis.__version__}"


def test_postgres_nearest_sentence_query_builds() -> None:
    """The paraphrase search on PostgreSQL crashed with AttributeError ('cosine_distance')
    the first time it ran in Docker: SQLite tests never build this query."""
    import numpy as np
    from sqlalchemy.dialects import postgresql

    from worker.sql_index import nearest_query

    sql = str(nearest_query(np.ones(384, dtype=np.float32), 7).compile(dialect=postgresql.dialect()))
    assert "<=>" in sql and "ORDER BY" in sql and "LIMIT" in sql
    # Excluded sources are filtered in SQL, before the LIMIT (found in the Docker audit).
    sql = str(nearest_query(np.ones(384, dtype=np.float32), 7, {"a", "b"}).compile(dialect=postgresql.dialect()))
    assert "NOT IN" in sql and sql.index("NOT IN") < sql.index("LIMIT")


def test_celery_app_loads() -> None:
    from worker.celery_app import app

    assert "worker.tasks.run_check" in app.conf.task_routes
