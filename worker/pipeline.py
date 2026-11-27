"""Job logic, independent of Celery so it can also run inline (local) and in tests.

One check = one job, run start to finish by one worker slot (at most
MAX_CONCURRENT_CHECKS at a time):

  extracting 5-35  ->  similarity 40-75  ->  AI writing 75-95  ->  done 100  (+ PDF report)

Reliability:
- A `running` check found after a crash is started again (each stage can run twice).
- An unexpected error on the first attempt puts the check back in the queue once
  (`final_attempt=False`); on the final attempt it is marked failed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from api.config import Settings, get_settings
from api.db import get_sessionmaker
from api.models import DocumentText, FlagRow, SimilarityMatchRow, SourceRow, SourceType, Status, Submission, utcnow
from engine.extract import ExtractionError, ExtractOptions, count_words, extract_document
from engine.similarity.check import SimilarityOptions, check_similarity
from engine.similarity.index import Encoder, build_entry
from engine.similarity.tokens import canonical_sha256
from worker import frozen
from worker.sql_index import SqlSourceIndex, store_entry, upsert_source
from worker.web_sources import discover_web_sources

log = logging.getLogger("hamzonics.pipeline")

EXTRACT_START, EXTRACT_END = 5, 35
SIM_START, SIM_END = 40, 75
AI_START, AI_END = 75, 95
STAGE_EXTRACTED = "extracted"
EXCERPT_MAX = 1500
INTERNAL_ERROR = "An internal error stopped this check. Please try again."


def run_check(submission_id: str, final_attempt: bool = True) -> None:
    """All stages one after the other."""
    if process_extraction(submission_id, final_attempt):
        process_analysis(submission_id, final_attempt)


def _save_progress(db, sub: Submission, value: int) -> None:  # type: ignore[no-untyped-def]
    # Progress is cosmetic: a busy database must never fail the check.
    try:
        sub.progress = value
        db.commit()
    except Exception:
        db.rollback()
        log.warning("could not save progress for %s", sub.id, exc_info=True)


def process_extraction(submission_id: str, final_attempt: bool = True) -> bool:
    """Extract clean text + integrity flags. Returns True if the next stage should run."""
    settings = get_settings()
    with get_sessionmaker()() as db:
        sub = db.get(Submission, submission_id)
        if sub is None or sub.status not in (Status.QUEUED, Status.RUNNING):
            log.info("skip submission %s (missing or already finished)", submission_id)
            return False
        if not Path(sub.file_path).exists() and db.get(DocumentText, sub.id) is not None and sub.result_key:
            # Re-run of a finished/interrupted check whose upload was already removed:
            # the extracted text is kept, so go straight to the analysis.
            sub.status, sub.stage, sub.progress, sub.error = Status.RUNNING, STAGE_EXTRACTED, EXTRACT_END, None
            db.commit()
            return True
        sub.status, sub.stage, sub.progress = Status.RUNNING, "extracting", EXTRACT_START
        sub.started_at = utcnow()
        sub.error = None
        db.commit()

        def on_progress(done: int, total: int) -> None:
            _save_progress(db, sub, EXTRACT_START + (EXTRACT_END - EXTRACT_START) * done // max(total, 1))

        try:
            doc = extract_document(
                Path(sub.file_path),
                sub.file_type,
                ExtractOptions(
                    pdf_backend=settings.pdf_backend,
                    ocr_languages=settings.ocr_languages,
                    ocr_min_chars=settings.ocr_min_chars_per_page,
                    ocr_dpi=settings.ocr_dpi,
                ),
                progress=on_progress,
            )
            words = count_words(doc.text)
            if words == 0:
                raise ExtractionError("No readable text was found in this document.")
            if words > settings.max_words:
                raise ExtractionError(
                    f"This document has {words:,} words. The limit is {settings.max_words:,} words per check."
                )

            existing = db.get(DocumentText, sub.id)
            if existing is None:
                db.add(DocumentText(submission_id=sub.id, clean_text=doc.text, offsets={"pages": doc.page_offsets}))
            else:
                existing.clean_text, existing.offsets = doc.text, {"pages": doc.page_offsets}
            sub.flags.clear()
            db.flush()
            for i, flag in enumerate(doc.flags):
                sub.flags.append(FlagRow(type=flag.type, position=i, count=flag.count, locations=flag.locations))
            sub.word_count = words
            sub.page_count = len(doc.pages)
            sub.ocr_pages = doc.ocr_page_count
            sub.text_sha256 = canonical_sha256(doc.text)
            # Which sources were searched is part of the key: switching on web search (or a new
            # provider) must give a fresh result, not the old one computed without it.
            sub.result_key = frozen.compute_result_key(
                sub.text_sha256, {**(sub.settings or {}), "sources": sources_fingerprint(settings)})
            sub.stage, sub.progress = STAGE_EXTRACTED, EXTRACT_END
            db.commit()
            return True
        except ExtractionError as exc:
            _fail(db, sub, str(exc))
            return False
        except Exception:
            log.exception("extraction crashed for submission %s", submission_id)
            _crashed(db, sub, final_attempt)
            raise


def sources_fingerprint(settings: Settings) -> str:
    """The set of source providers and detectors a result depends on (no secrets)."""
    parts = sorted(n.strip().lower() for n in settings.free_sources.split(",") if n.strip())
    if settings.core_api_key:
        parts.append("+core-key")
    if settings.searxng_url:
        parts.append("+searxng")
    if settings.serper_api_key:
        parts.append("+serper")
    if settings.brave_api_key:
        parts.append("+brave")
    if settings.google_cse_key and settings.google_cse_cx:
        parts.append("+google")
    parts.append(f"semantic={settings.enable_semantic}")
    parts.append(f"ai={settings.enable_ai}:{settings.ai_threshold}:{settings.ai_possible_threshold}")
    if settings.ai_confirm_enabled:
        parts.append(f"confirm={settings.ai_confirm_model}@{settings.ai_confirm_model_revision[:7]}:"
                     f"{settings.ai_confirm_threshold}:{settings.ai_threshold_unconfirmed}")
    if settings.ai2_enabled:
        parts.append(f"ai2={settings.ai2_model}@{settings.ai2_model_revision[:7]}:{settings.ai2_rule}"
                     + (":int8" if settings.ai2_quantize else ""))
    return ",".join(parts)


def get_encoder(settings: Settings) -> Encoder | None:
    if not settings.enable_semantic:
        return None
    try:
        from engine.similarity.semantic import get_embedder

        return get_embedder(settings.similarity_model, settings.similarity_model_revision, settings.torch_threads)
    except (ImportError, OSError):
        # PyTorch cannot load (e.g. old Visual C++ runtime on Windows): exact and
        # near matching still work, only paraphrase matching is skipped.
        log.warning("paraphrase model unavailable; continuing without it", exc_info=True)
        return None


def process_analysis(submission_id: str, final_attempt: bool = True) -> None:
    settings = get_settings()
    with get_sessionmaker()() as db:
        sub = db.get(Submission, submission_id)
        if sub is None or sub.status != Status.RUNNING or sub.stage not in (STAGE_EXTRACTED, "similarity", "ai"):
            log.info("skip analysis for %s", submission_id)
            return
        doc = db.get(DocumentText, sub.id)
        assert doc is not None and sub.result_key is not None
        sub.stage, sub.progress = "similarity", SIM_START
        db.commit()
        encoder = None
        try:
            # No write may stay open during the (long) computation: on SQLite it would
            # block every upload. Old match rows are replaced inside frozen.apply().
            with frozen.result_lock(db, sub.result_key):
                result = frozen.load(db, sub.result_key)
                if result is None:
                    encoder = get_encoder(settings)
                    computed = _compute_similarity(db, sub, doc.clean_text, settings, encoder)
                    sub.stage = "ai"
                    _save_progress(db, sub, AI_START)
                    computed["ai"] = _compute_ai(db, sub, doc.clean_text, settings)
                    if computed["web_search"]["web_search"] in ("unavailable", "partial"):
                        # Search engines blocked us: never freeze an incomplete result, so a
                        # later check of the same text searches again.
                        result = computed
                    else:
                        result = frozen.store(db, sub.result_key, computed)
                frozen.apply(db, sub, doc.clean_text, result)
                sub.settings = {**(sub.settings or {}), "_web_search": result.get("web_search", {"web_search": "off"})}
                db.flush()
                # The stored score is the one the report shows by default (bibliography filtered).
                from api.services import similarity_view

                sub.similarity_percent = similarity_view(db, sub).percent
                sub.progress = AI_END
                db.commit()

            # Add this document to the repository AFTER matching, so it never matches itself.
            if sub.repository_opt_in:
                # Another person's report shows this only as "Submitted works" with a date:
                # never the file name.
                row, changed = upsert_source(
                    db, type=SourceType.SUBMISSION,
                    title=f"Submitted to {settings.app_name} on {utcnow():%Y-%m-%d}", text=doc.clean_text,
                    submission_id=sub.id,
                )
                if changed:
                    encoder = encoder or get_encoder(settings)
                    store_entry(db, row, build_entry(doc.clean_text, encoder))

            sub.status, sub.stage, sub.progress = Status.DONE, "done", 100
            sub.finished_at = utcnow()
            db.commit()
        except Exception:
            log.exception("analysis crashed for submission %s", submission_id)
            _crashed(db, sub, final_attempt)
            raise

        # The uploaded file is not needed any more (the clean text is kept for the report).
        Path(sub.file_path).unlink(missing_ok=True)

        # The PDF is a convenience copy of the online report: if Chromium fails, the check
        # stays done and the PDF is built again on the first download.
        if settings.generate_pdf_in_pipeline:
            try:
                from worker.report import generate_report

                generate_report(db, sub)
            except Exception:
                log.exception("PDF report failed for submission %s (will retry on download)", submission_id)


def _compute_similarity(db, sub: Submission, clean_text: str, settings: Settings, encoder: Encoder | None) -> dict:  # type: ignore[no-untyped-def]
    """Fresh similarity computation, returned in frozen-result form."""
    from engine.similarity.sentences import split_sentences

    def web_progress(done: int, total: int) -> None:
        _save_progress(db, sub, SIM_START + 20 * done // max(total, 1))

    web_status = discover_web_sources(db, clean_text, split_sentences(clean_text), settings, encoder, progress=web_progress)
    _save_progress(db, sub, SIM_START + 22)
    result = check_similarity(
        clean_text,
        SqlSourceIndex(db),
        encoder,
        SimilarityOptions(semantic_threshold=settings.semantic_threshold, max_candidates=settings.max_candidate_sources),
        exclude=_self_sources(db, sub),
    )
    rows = []
    for m in result.matches:
        src = result.sources[m.source_key]
        rows.append(SimilarityMatchRow(
            source_key=m.source_key, word_start=m.word_start, word_end=m.word_end,
            source_start=m.source_start, source_end=m.source_end, match_type=m.match_type,
            match_group=m.group, score=m.score, source_type=src.type, source_title=src.title[:500],
            source_url=src.url, source_excerpt=src.text[m.source_start : m.source_end][:EXCERPT_MAX],
        ))
    snap = frozen.snapshot(rows, result.score.percent)
    snap["web_search"] = web_status
    return snap


def _compute_ai(db, sub: Submission, clean_text: str, settings: Settings) -> dict:  # type: ignore[no-untyped-def]
    if not settings.enable_ai:
        return {"available": False, "message": "AI-writing detection is switched off on this server.", "segments": []}
    from engine.ai import AIOptions, detect_ai
    from engine.ai.model import get_scorer

    scorer = None
    second_only = settings.ai2_enabled and settings.ai2_rule == "only"
    if second_only:
        # Second detector alone: the first model's weights are never loaded (saves RAM).
        try:
            from engine.ai.combined import SecondOnlyScorer
            from engine.ai.desklib import get_desklib
            from engine.ai.model import get_token_counter

            scorer = SecondOnlyScorer(
                get_token_counter(settings.ai_model, settings.ai_model_revision, Path(settings.model_dir)),
                get_desklib(settings.ai2_model, settings.ai2_model_revision, Path(settings.model_dir),
                            settings.torch_threads, settings.ai2_quantize))
        except Exception:
            log.exception("second AI model could not be loaded; using the first instead")
    if scorer is None:
        try:
            scorer = get_scorer(settings.ai_model, settings.ai_model_revision, Path(settings.model_dir))
        except Exception:
            log.exception("AI model could not be loaded")
            return {"available": False, "segments": [],
                    "message": "AI-writing detection is temporarily unavailable (the model could not be loaded)."}

    if settings.ai2_enabled and not second_only:
        # Second detector (needs PyTorch). If it cannot load, the check continues with the first.
        try:
            from engine.ai.combined import CombinedScorer
            from engine.ai.desklib import get_desklib

            second = get_desklib(settings.ai2_model, settings.ai2_model_revision, Path(settings.model_dir),
                                 settings.torch_threads, settings.ai2_quantize)
            scorer = CombinedScorer(scorer, second, settings.ai2_rule)  # type: ignore[assignment]
        except Exception:
            log.exception("second AI model could not be loaded; using the first only")

    threshold = settings.ai_threshold
    if settings.ai_confirm_enabled:
        # Confirming model: removes the primary model's false alarms on human text. If it cannot
        # load, the primary model alone must pass a much stricter threshold (never a looser check).
        try:
            from engine.ai.combined import GateScorer
            from engine.ai.superannotate import get_superannotate

            confirm = get_superannotate(settings.ai_confirm_model, settings.ai_confirm_model_revision,
                                        Path(settings.model_dir), settings.torch_threads)
            scorer = GateScorer(scorer, confirm, settings.ai_threshold, settings.ai_confirm_threshold)  # type: ignore[assignment]
        except Exception:
            log.exception("confirming AI model could not be loaded; using the stricter single-model threshold")
            threshold = max(settings.ai_threshold, settings.ai_threshold_unconfirmed)

    def on_progress(done: int, total: int) -> None:
        _save_progress(db, sub, AI_START + (AI_END - AI_START) * done // max(total, 1))

    result = detect_ai(clean_text, scorer, AIOptions(
        threshold=threshold, possible_threshold=settings.ai_possible_threshold,
        window_tokens=settings.ai_window_tokens, overlap=settings.ai_overlap, min_words=settings.ai_min_words,
    ), progress=on_progress)
    return result.to_json()


def _self_sources(db, sub: Submission) -> set[str]:  # type: ignore[no-untyped-def]
    """Repository documents that ARE this document: the submission itself and earlier
    uploads of exactly the same text (re-checking your own draft must not match itself)."""
    rows = db.scalars(
        select(SourceRow.id).where(
            SourceRow.type == SourceType.SUBMISSION,
            (SourceRow.submission_id == sub.id) | (SourceRow.text_sha256 == sub.text_sha256),
        )
    ).all()
    return set(rows)


def _crashed(db, sub: Submission, final_attempt: bool) -> None:  # type: ignore[no-untyped-def]
    if final_attempt:
        _fail(db, sub, INTERNAL_ERROR)
        return
    # One automatic retry: back to the queue.
    db.rollback()
    sub.status, sub.stage, sub.progress, sub.error = Status.QUEUED, "retrying", 0, None
    db.commit()


def _fail(db, sub: Submission, message: str) -> None:  # type: ignore[no-untyped-def]
    db.rollback()
    sub.status, sub.stage, sub.error = Status.FAILED, "failed", message
    sub.finished_at = utcnow()
    db.commit()
