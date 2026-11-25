"""Test configuration: SQLite database, inline job runner, no live services."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before api modules read settings.
os.environ.update(
    {
        "ENV": "test",
        "SECRET_KEY": "test-secret-" + "x" * 40,
        "JOB_RUNNER": "inline",
        "INLINE_SYNC": "true",
        "PUBLIC_BASE_URL": "http://testserver",
        # API tests use fingerprints only (fast); embedding tests live in tests/engine.
        "ENABLE_SEMANTIC": "false",
        # The real AI model is tested in tests/engine/test_ai.py; API tests use a fake scorer.
        "ENABLE_AI": "false",
        # The confirming model (GateScorer) is tested in tests/engine/test_ai.py with fakes.
        "AI_CONFIRM_ENABLED": "false",
        # Tests never call live services; providers are tested with mocked HTTP.
        "FREE_SOURCES": "",
        # PDFs are built on download in tests (tests/api/test_report.py) to keep the suite fast.
        "GENERATE_PDF_IN_PIPELINE": "false",
        "CHECKS_PER_IP_PER_HOUR": "0",
    }
)


@pytest.fixture()
def app_env(tmp_path: Path) -> Iterator[Path]:
    from api.config import get_settings
    from api.db import init_engine
    from api.models import Base

    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    os.environ["UPLOAD_DIR"] = str(tmp_path / "uploads")
    os.environ["REPORT_DIR"] = str(tmp_path / "reports")
    get_settings.cache_clear()
    engine = init_engine()
    Base.metadata.create_all(engine)
    yield tmp_path
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture()
def client(app_env: Path):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from api.main import create_app

    with TestClient(create_app()) as c:
        yield c
