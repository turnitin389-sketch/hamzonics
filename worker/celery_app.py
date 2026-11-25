"""Celery application. One queue, `checks`; run the worker with
--concurrency=$MAX_CONCURRENT_CHECKS so that many checks run at once."""

from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import worker_init

# The Rust tokenizers are created before the pool forks (see _preload_ai_models).
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from api.config import get_settings

logging.getLogger("httpx").setLevel(logging.WARNING)
# trafilatura logs every non-HTML page it is given at ERROR level ("parsed tree length").
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)

settings = get_settings()

app = Celery("hamzonics", broker=settings.redis_url, backend=settings.redis_url, include=["worker.tasks"])
app.conf.update(
    task_acks_late=True,  # a check is never lost if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # strict arrival order: a busy slot never holds a waiting job
    task_time_limit=settings.job_time_limit_s,
    task_soft_time_limit=max(settings.job_time_limit_s - 30, 30),
    task_routes={"worker.tasks.run_check": {"queue": "checks"}, "worker.tasks.maintenance": {"queue": "checks"}},
    task_default_queue="checks",
    broker_connection_retry_on_startup=True,
    # Redis: a task not acknowledged within this time is given to another worker. Must be
    # longer than the slowest check, or a long check would run twice.
    broker_transport_options={"visibility_timeout": settings.job_time_limit_s * 2},
    # Housekeeping (stuck jobs, expired checks). Runs inside the worker with `-B`.
    beat_schedule={"maintenance": {"task": "worker.tasks.maintenance", "schedule": 900.0}},
    result_expires=3600,
    timezone="UTC",
)


@worker_init.connect
def _preload_ai_models(**_: object) -> None:
    """Load the AI models ONCE in the parent process, before the pool forks: the child
    processes then share the weights (copy-on-write) instead of each loading its own copy
    (3 checks at once: ~2 GB instead of ~6 GB). Only loading happens here, no inference,
    so no thread pools exist yet when the children are forked."""
    from pathlib import Path

    if settings.enable_semantic:
        try:
            from engine.similarity.semantic import get_embedder

            get_embedder(settings.similarity_model, settings.similarity_model_revision, settings.torch_threads)
        except Exception:
            logging.getLogger(__name__).exception("paraphrase model preload failed; loads on first use")
    if not settings.enable_ai:
        return
    try:
        from engine.ai.model import get_scorer

        get_scorer(settings.ai_model, settings.ai_model_revision, Path(settings.model_dir))
        if settings.ai_confirm_enabled:
            from engine.ai.superannotate import get_superannotate

            get_superannotate(settings.ai_confirm_model, settings.ai_confirm_model_revision,
                              Path(settings.model_dir), settings.torch_threads)
    except Exception:  # the check itself reports / falls back if a model cannot load
        logging.getLogger(__name__).exception("AI model preload failed; models load on first use")
