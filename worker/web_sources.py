"""Find, cache and index live sources (see engine/similarity/web.py).

Credit-saving order (paid search APIs cost money per search):
1. Free sources (Wikipedia, arXiv, Europe PMC, OpenAlex, SearXNG ...) are searched first,
   in parallel, and everything they find is indexed.
2. Paid search (Serper / Brave / Google) is used only for phrases that are NOT already found
   in an indexed web/publication source, a few phrases at a time. After every round the
   remaining phrases are checked again, so once the copied page is found (it usually contains
   the other phrases too) no more credits are spent.
3. Every web search answer is cached for SEARCH_CACHE_DAYS: the same phrase never costs twice.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.config import Settings
from api.db import get_sessionmaker
from api.models import FingerprintRow, SearchCache, SourceRow, SourceType, as_utc, utcnow
from engine.similarity.fingerprint import gram_hashes
from engine.similarity.index import Encoder, build_entry
from engine.similarity.tokens import tokenize
from engine.similarity.web import DocumentProvider, FoundDocument, build_providers, distinctive_sentences
from worker.sql_index import store_entry, upsert_source

log = logging.getLogger("hamzonics.web")
PAID_BATCH = 6  # paid phrases searched per round before re-checking what is already found


def paid_query_count(words: int, settings: Settings) -> int:
    """Paid searches for a document of `words` words: one per PAID_SEARCH_WORDS_PER_QUERY words,
    between PAID_SEARCH_MAX_QUERIES and PAID_SEARCH_QUERY_CAP."""
    per = max(1, settings.paid_search_words_per_query)
    low = max(0, settings.paid_search_max_queries)
    return max(low, min(max(low, settings.paid_search_query_cap), -(-words // per)))


def providers_from_settings(settings: Settings) -> list[DocumentProvider]:
    from worker.key_pool import KeyPool

    names = [n.strip().lower() for n in settings.free_sources.split(",") if n.strip()]
    langs = [lang.strip() for lang in settings.wikipedia_langs.split(",") if lang.strip()]
    serper_pool = KeyPool("serper", settings.serper_api_key)
    providers = build_providers(
        names, langs, settings.searxng_url,
        openalex_key=settings.openalex_api_key, semanticscholar_key=settings.semanticscholar_api_key,
        core_key=settings.core_api_key, brave_key=settings.brave_api_key,
        google_key=settings.google_cse_key, google_cx=settings.google_cse_cx,
        serper_key=serper_pool if serper_pool else "", fetch_fulltext=settings.web_fetch_pdfs,
    )
    for p in providers:
        if getattr(p, "is_web_search", False):
            p.cache_get, p.cache_put = _cache_functions(settings.search_cache_days)
    return providers


# ------------------------------------------------------------------ search result cache


def _query_hash(phrase: str) -> str:
    return hashlib.sha256(" ".join(phrase.lower().split()).encode()).hexdigest()


def _cache_functions(days: int):  # type: ignore[no-untyped-def]
    def get(provider: str, phrase: str) -> list[str] | None:
        if days <= 0:
            return None
        with get_sessionmaker()() as db:
            row = db.scalar(select(SearchCache).where(SearchCache.provider == provider,
                                                      SearchCache.query_hash == _query_hash(phrase)))
            if row is None or as_utc(row.created_at) < utcnow() - timedelta(days=days):
                return None
            return list(row.urls)

    def put(provider: str, phrase: str, urls: list[str]) -> None:
        if days <= 0:
            return
        with get_sessionmaker()() as db:
            row = db.scalar(select(SearchCache).where(SearchCache.provider == provider,
                                                      SearchCache.query_hash == _query_hash(phrase)))
            if row is None:
                db.add(SearchCache(provider=provider, query_hash=_query_hash(phrase), urls=urls))
            else:
                row.urls, row.created_at = urls, utcnow()
            try:
                db.commit()
            except IntegrityError:  # another check cached the same phrase at the same moment
                db.rollback()

    return get, put


# ------------------------------------------------------------------ "already found?" check


def phrase_already_found(db: Session, phrase: str) -> bool:
    """True if an indexed web page or publication already contains this phrase (two or more
    of its 5-word fingerprints in one source). Earlier submissions do not count: they do not
    replace finding the original on the web."""
    hashes = list(set(gram_hashes(tokenize(phrase))))
    if len(hashes) < 2:
        return False
    best = db.execute(
        select(FingerprintRow.source_id, func.count(func.distinct(FingerprintRow.hash)).label("n"))
        .join(SourceRow, SourceRow.id == FingerprintRow.source_id)
        .where(FingerprintRow.hash.in_(hashes), SourceRow.type != SourceType.SUBMISSION)
        .group_by(FingerprintRow.source_id)
        .order_by(func.count(func.distinct(FingerprintRow.hash)).desc())
        .limit(1)
    ).first()
    return best is not None and best[1] >= 2


# ------------------------------------------------------------------ main


def _search(jobs: list[tuple[DocumentProvider, str]], settings: Settings, deadline: float,
            progress: Callable[[], None] | None) -> tuple[dict[str, FoundDocument], dict[str, int]]:
    def run(job: tuple[DocumentProvider, str]) -> list[FoundDocument]:
        provider, phrase = job
        try:
            return provider.find(phrase, settings.web_results_per_query)
        except Exception:  # an outage of a free service must never fail a check
            log.warning("provider %s failed", provider.name, exc_info=True)
            return []

    found: dict[str, FoundDocument] = {}
    hits: dict[str, int] = {}
    if not jobs:
        return found, hits
    # One slow website must never hold a check: after the time budget we use what we have
    # (unfinished searches keep running in the background and are ignored).
    pool = ThreadPoolExecutor(max_workers=8)
    futures = [pool.submit(run, job) for job in jobs]
    try:
        for fut in as_completed(futures, timeout=max(1.0, deadline - time.monotonic())):
            for d in fut.result():
                found.setdefault(d.url, d)
                hits[d.url] = hits.get(d.url, 0) + 1
            if progress:
                progress()
    except FuturesTimeout:
        log.warning("live sources: time budget reached")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return found, hits


def _index(db: Session, found: dict[str, FoundDocument], hits: dict[str, int], settings: Settings,
           encoder: Encoder | None, limit: int) -> int:
    # Documents found by more phrases first: they are the likeliest real sources.
    ranked = sorted(found, key=lambda u: (-hits[u], u))[:limit]
    fresh_after = utcnow() - timedelta(days=settings.web_cache_days)
    indexed = 0
    for url in ranked:
        doc = found[url]
        cached = db.scalar(select(SourceRow).where(SourceRow.type == doc.source_type, SourceRow.url == url))
        # A fresh cached copy is kept unless the newly fetched text is longer (better extraction).
        if cached is not None and as_utc(cached.cached_at) >= fresh_after and cached.word_count >= len(doc.text.split()):
            continue
        row, changed = upsert_source(db, type=doc.source_type, corpus=doc.provider, title=doc.title,
                                     text=doc.text, url=url)
        if changed:
            # Live documents were found by searching the submission's own wording, so exact
            # matching finds them; sentence embeddings for every page would cost ~6 minutes
            # per check on one CPU (measured 2026-11-22: ~19 sentences/s).
            store_entry(db, row, build_entry(doc.text, encoder if settings.web_embed_sources else None))
            indexed += 1
        db.commit()
    return indexed


def discover_web_sources(
    db: Session,
    text: str,
    sentences: list[tuple[int, int]],
    settings: Settings,
    encoder: Encoder | None,
    providers: list[DocumentProvider] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Search, cache and index live sources. Returns a status dict:
    indexed, web_search ("off" | "ok" | "partial" | "unavailable"), web_ok, web_failed,
    paid_searches (credits spent), paid_skipped (phrases already found, no credit spent)."""
    providers = providers if providers is not None else providers_from_settings(settings)
    status = {"indexed": 0, "web_search": "off", "web_ok": 0, "web_failed": 0, "paid_searches": 0, "paid_skipped": 0}
    if not providers:
        return status
    deadline = time.monotonic() + settings.web_time_budget_s
    free = [p for p in providers if not getattr(p, "paid", False)]
    paid = [p for p in providers if getattr(p, "paid", False)]
    phrases = distinctive_sentences(text, sentences, n=settings.web_search_max_queries)
    paid_phrases = distinctive_sentences(text, sentences, n=paid_query_count(len(text.split()), settings)) if paid else []
    total_jobs = len(free) * len(phrases) + len(paid) * len(paid_phrases)
    done = [0]

    def tick() -> None:
        done[0] += 1
        if progress:
            progress(min(done[0], total_jobs), max(total_jobs, 1))

    # 1. Free sources, all at once.
    found, hits = _search([(p, ph) for p in free for ph in phrases], settings, deadline, tick)
    indexed = _index(db, found, hits, settings, encoder, settings.web_max_pages)

    # 2. Paid search only for what is still missing, a few phrases per round.
    pending = list(paid_phrases)
    skipped = 0
    while pending and paid and time.monotonic() < deadline:
        still = [ph for ph in pending if not phrase_already_found(db, ph)]
        skipped += len(pending) - len(still)
        for _ in range((len(pending) - len(still)) * len(paid)):
            tick()
        pending = still
        if not pending:
            break
        batch, pending = pending[:PAID_BATCH], pending[PAID_BATCH:]
        f2, h2 = _search([(p, ph) for p in paid for ph in batch], settings, deadline, tick)
        for url, d in f2.items():
            found.setdefault(url, d)
            hits[url] = hits.get(url, 0) + h2[url]
        indexed += _index(db, f2, h2, settings, encoder, settings.web_max_pages)

    for p in paid:
        flush = getattr(getattr(p, "keys", None), "flush_usage", None)
        if flush:
            flush()

    web = [p for p in providers if getattr(p, "is_web_search", False)]
    # A paid API is the reliable search: when one is configured, judge by it alone; failures
    # of the free SearXNG engines alongside it do not make a check incomplete.
    judged = paid or web
    ok = sum(getattr(p, "ok", 0) + getattr(p, "cache_hits", 0) for p in judged)
    failed = sum(getattr(p, "failed", 0) for p in judged)
    if web:
        if ok == 0 and failed == 0:
            # nothing needed searching (everything already found) -> fine; else nothing answered
            status["web_search"] = "ok" if paid and skipped else "unavailable"
        elif ok == 0:
            status["web_search"] = "unavailable"
        elif failed > ok:  # most searches blocked
            status["web_search"] = "partial"
        else:
            status["web_search"] = "ok"
    paid_used = sum(getattr(p, "ok", 0) + getattr(p, "failed", 0) for p in paid)
    status.update(indexed=indexed, web_ok=ok, web_failed=failed, paid_searches=paid_used, paid_skipped=skipped)
    log.info("live sources: %d free phrases x %d free providers, paid: %d searches, %d phrases skipped (already found); "
             "%d documents found, %d indexed; web search %s", len(phrases), len(free), paid_used, skipped,
             len(found), indexed, status["web_search"])
    return status
