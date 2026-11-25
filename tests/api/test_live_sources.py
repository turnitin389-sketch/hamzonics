"""The pipeline finds a copied paragraph through a (mocked) live source."""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.similarity.web import FoundDocument
from tests.api.test_similarity_api import _paste
from tests.engine.test_similarity import AGRI, COPIED


class FakeWikipedia:
    name = "wikipedia-en"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def find(self, phrase: str, limit: int) -> list[FoundDocument]:
        self.queries.append(phrase)
        return [FoundDocument(AGRI["url"], AGRI["title"], AGRI["text"], "web", self.name)]


def test_live_source_found_and_cached(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = FakeWikipedia()
    monkeypatch.setattr("worker.web_sources.providers_from_settings", lambda settings: [fake])

    s = _paste(client, COPIED, opt_in=False)
    assert s["similarity_percent"] == 100.0
    assert fake.queries, "no phrases were searched"
    sim = client.get(f"/api/submissions/{s['id']}/similarity").json()
    assert sim["sources"][0]["type"] == "web"
    assert sim["sources"][0]["url"] == AGRI["url"]

    from api.db import get_sessionmaker
    from api.models import SourceRow

    with get_sessionmaker()() as db:
        assert db.query(SourceRow).filter(SourceRow.url == AGRI["url"]).count() == 1
    # Same text again: the frozen result is reused (identical score).
    assert _paste(client, COPIED, opt_in=False)["similarity_percent"] == 100.0


def test_blocked_web_search_is_reported_and_not_frozen(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Search engines blocked us (CAPTCHA / 429): the report must say so, and the result must
    not be frozen, so checking the same text later searches again (found in local testing)."""
    import httpx

    from engine.similarity.web import SearxngProvider

    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [["google", "CAPTCHA"]]})

    searx = SearxngProvider("http://searx.test", httpx.Client(transport=httpx.MockTransport(blocked)))
    monkeypatch.setattr("worker.web_sources.providers_from_settings", lambda settings: [searx])
    s = _paste(client, COPIED, opt_in=False)
    sim = client.get(f"/api/submissions/{s['id']}/similarity").json()
    assert sim["web_search"] == "unavailable" and "not available" in sim["web_search_message"]

    from api.db import get_sessionmaker
    from api.models import FrozenResult

    with get_sessionmaker()() as db:
        assert db.query(FrozenResult).count() == 0

    # Search works again: the same text is searched again and the source is found.
    monkeypatch.setattr("worker.web_sources.providers_from_settings", lambda settings: [FakeWikipedia()])
    s2 = _paste(client, COPIED, opt_in=False)
    sim2 = client.get(f"/api/submissions/{s2['id']}/similarity").json()
    assert s2["similarity_percent"] == 100.0 and sim2["web_search"] == "off"


def test_working_paid_search_is_not_marked_incomplete_by_blocked_free_engines(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    from engine.similarity.web import SearxngProvider, SerperProvider

    blocked = SearxngProvider("http://searx.test", httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"results": [], "unresponsive_engines": [["google", "CAPTCHA"]]}))))
    serper = SerperProvider("k", httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"organic": []}))))
    monkeypatch.setattr("worker.web_sources.providers_from_settings", lambda settings: [blocked, serper])
    s = _paste(client, COPIED, opt_in=False)
    sim = client.get(f"/api/submissions/{s['id']}/similarity").json()
    assert sim["web_search"] == "ok" and sim["web_search_message"] == ""


def test_slow_source_cannot_hold_a_check(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import time

    from api.config import get_settings

    class Hanging:
        name = "slow"

        def find(self, phrase: str, limit: int) -> list[FoundDocument]:
            time.sleep(5)
            return []

    monkeypatch.setenv("WEB_TIME_BUDGET_S", "1")
    get_settings.cache_clear()
    monkeypatch.setattr("worker.web_sources.providers_from_settings", lambda settings: [Hanging(), FakeWikipedia()])
    t0 = time.time()
    s = _paste(client, COPIED + " A different ending sentence for this test only.", opt_in=False)
    assert time.time() - t0 < 4.5
    assert s["similarity_percent"] > 90  # the fast source was still used
