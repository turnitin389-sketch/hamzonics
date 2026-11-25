"""Similarity through the API: corpus matches, repository, no self-match, filters, by-type."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.test_flow import paste
from tests.engine.test_similarity import AGRI, COPIED, ORIGINAL_ESSAY


def _seed_corpus() -> None:
    from api.db import get_sessionmaker
    from api.models import SourceType
    from engine.similarity.index import build_entry
    from worker.sql_index import store_entry, upsert_source

    with get_sessionmaker()() as db:
        row, _ = upsert_source(db, type=SourceType.WEB, corpus="wikipedia-en", title=AGRI["title"],
                               text=AGRI["text"], url=AGRI["url"])
        store_entry(db, row, build_entry(AGRI["text"], None))
        db.commit()


def _paste(client: TestClient, text: str, opt_in: bool = True) -> dict:
    r = paste(client, text, opt_in)
    assert r.status_code == 202, r.text
    s = client.get(f"/api/submissions/{r.json()['id']}").json()
    assert s["status"] == "done", s
    return s


def mixed_text() -> str:
    first = COPIED.split(". ")[0] + "."
    return f"{ORIGINAL_ESSAY}\n\nAs one source puts it, “{first}” (FAO, 2020). {COPIED.split('. ', 2)[2]}"


def test_corpus_match_and_filters(client: TestClient) -> None:
    _seed_corpus()
    s = _paste(client, mixed_text())
    assert s["similarity_percent"] > 20

    full = client.get(f"/api/submissions/{s['id']}/similarity").json()
    assert full["percent"] == s["similarity_percent"]  # stored score = report default
    assert full["exclude_bibliography"] is True
    assert full["sources"][0]["title"] == "Agriculture in Pakistan"
    assert full["sources"][0]["url"].startswith("https://en.wikipedia.org/")
    assert full["by_type"]["web"] == full["percent"] and full["by_type"]["corpus"] == 0.0
    assert "cited_and_quoted" in full["groups"]
    run = full["runs"][0]
    assert run["source_excerpt"] and run["end"] > run["start"]

    no_quotes = client.get(f"/api/submissions/{s['id']}/similarity", params={"exclude_quotes": "true"}).json()
    assert no_quotes["matched_words"] == full["matched_words"] - full["groups"]["cited_and_quoted"]
    key = full["sources"][0]["source_key"]
    none = client.get(f"/api/submissions/{s['id']}/similarity", params={"exclude_source": key}).json()
    assert none["percent"] == 0.0


def test_bibliography_is_filtered_by_default(client: TestClient) -> None:
    _seed_corpus()
    text = f"{ORIGINAL_ESSAY}\n\n{ORIGINAL_ESSAY}\n\nReferences\n\n{COPIED}"
    s = _paste(client, text, opt_in=False)
    default = client.get(f"/api/submissions/{s['id']}/similarity").json()
    with_bib = client.get(f"/api/submissions/{s['id']}/similarity", params={"exclude_bibliography": "false"}).json()
    assert default["percent"] == 0.0 and with_bib["percent"] > 0


def test_reupload_never_matches_itself_but_copies_are_found(client: TestClient) -> None:
    first = _paste(client, ORIGINAL_ESSAY)
    assert first["similarity_percent"] == 0.0
    again = _paste(client, ORIGINAL_ESSAY)  # the same text again (e.g. re-checking a draft)
    assert again["similarity_percent"] == 0.0

    # Someone else hands in the essay with an extra paragraph: the repository copy is found.
    copy = _paste(client, ORIGINAL_ESSAY + "\n\nI also added this closing paragraph about my own village and its farms.")
    assert copy["similarity_percent"] > 80
    sim = client.get(f"/api/submissions/{copy['id']}/similarity").json()
    assert {s["type"] for s in sim["sources"]} == {"submission"}
    # Other people's file names are never shown.
    assert sim["sources"][0]["title"].startswith("Submitted to")


def test_opt_out_is_not_stored_in_repository(client: TestClient) -> None:
    _paste(client, ORIGINAL_ESSAY, opt_in=False)
    longer = _paste(client, ORIGINAL_ESSAY + "\n\nAnd one more sentence that I wrote myself today.")
    assert longer["similarity_percent"] == 0.0
