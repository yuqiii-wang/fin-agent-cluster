"""PerfIngest Celery application — dedicated to bulk token production.

This app is intentionally isolated from :mod:`backend.streaming.celery_app`
so that perf-test ingest workers:

* Use separate Redis DB indices (broker DB 3, backend DB 4) to avoid
  key-space collisions with the main streaming workers (DB 1, DB 2).
* Can be scaled and tuned independently (gevent concurrency, prefetch, etc.).
* Do not interfere with production graph-event consumers.

Running the PerfIngest workers
-------------------------------
From the project root::

    celery -A backend.graph.agents.perf_test.celery_ingest.celery_app.perf_ingest_app \\
           worker --loglevel=info

Add beat for stall-recovery::

    celery -A backend.graph.agents.perf_test.celery_ingest.celery_app.perf_ingest_app \\
           worker --beat --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from backend.config import get_settings
from backend.graph.agents.perf_test.celery_ingest.config import (
    PERF_INGEST_BACKEND_DB,
    PERF_INGEST_BEAT_INTERVAL,
    PERF_INGEST_BROKER_DB,
    PERF_INGEST_MAX_RETRIES,
    PERF_INGEST_RETRY_DELAY,
)


def _broker_url(base_url: str, db: int) -> str:
    """Append *db* index to *base_url*, stripping any existing DB suffix.

    Args:
        base_url: Base Redis URL, e.g. ``redis://127.0.0.1:6379``.
        db:       Zero-based Redis database index to append.

    Returns:
        URL with database appended, e.g. ``redis://127.0.0.1:6379/3``.
    """
    url = base_url.rstrip("/")
    parts = url.rsplit("/", 1)
    if len(parts) == 2 and parts[1].isdigit():
        url = parts[0]
    return f"{url}/{db}"


def create_perf_ingest_app() -> Celery:
    """Build and return the PerfIngest Celery application.

    Beat schedule includes only the stall-recovery task.  The main ingest
    tasks are dispatched on-demand by :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest`
    and then self-chain (drain-first) until a session is exhausted.

    Returns:
        Fully configured :class:`celery.Celery` instance.
    """
    settings = get_settings()
    base = settings.DATABASE_REDIS_URL

    app = Celery(
        "perf_ingest",
        broker=_broker_url(base, PERF_INGEST_BROKER_DB),
        backend=_broker_url(base, PERF_INGEST_BACKEND_DB),
        include=["backend.graph.agents.perf_test.celery_ingest.tasks"],
    )

    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        # Keep root logger in FastAPI's dictConfig control.
        worker_hijack_root_logger=False,
        # Prefetch = 1: one ingest task per greenlet to avoid one worker
        # hoarding multiple sessions (would break drain-first focus).
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        task_default_retry_delay=PERF_INGEST_RETRY_DELAY,
        task_max_retries=PERF_INGEST_MAX_RETRIES,
        beat_schedule={
            "perf-ingest-recover-stalled": {
                "task": "backend.graph.agents.perf_test.celery_ingest.tasks.recover_stalled_streams",
                "schedule": PERF_INGEST_BEAT_INTERVAL,
            },
        },
    )

    return app


perf_ingest_app: Celery = create_perf_ingest_app()

__all__ = ["perf_ingest_app"]
