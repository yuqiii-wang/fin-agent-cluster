"""Celery application for Redis Streams background workers.

Workers batch-consume each Redis Stream topic via consumer groups.  The beat
scheduler re-enqueues polling tasks at a fixed interval.

Broker: ``DATABASE_REDIS_URL`` DB 1 — Backend: ``DATABASE_REDIS_URL`` DB 2
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab  # noqa: F401 — available for callers
from celery.signals import after_setup_logger, after_setup_task_logger

from backend.config import get_settings
from backend.streaming.config import (
    ACTIVE_TOPICS,
    CELERY_BACKEND_DB,
    CELERY_BROKER_DB,
    CELERY_WORKER_CONFIG,
)
from backend.streaming.log_filters import CeleryTaskSummaryFilter

# One shared filter instance per process — keeps counts consistent across
# the celery logger and the task logger.
_task_summary_filter = CeleryTaskSummaryFilter()


@after_setup_logger.connect
def _attach_summary_filter_to_celery_logger(logger, **kwargs) -> None:  # type: ignore[misc]
    """Attach the summary filter to the root Celery logger after setup."""
    for handler in logger.handlers:
        handler.addFilter(_task_summary_filter)


@after_setup_task_logger.connect
def _attach_summary_filter_to_task_logger(logger, **kwargs) -> None:  # type: ignore[misc]
    """Attach the summary filter to the per-task logger after setup."""
    for handler in logger.handlers:
        handler.addFilter(_task_summary_filter)


def _broker_url(base_url: str, db: int) -> str:
    """Return *base_url* with the Redis DB index appended."""
    url = base_url.rstrip("/")
    parts = url.rsplit("/", 1)
    if len(parts) == 2 and parts[1].isdigit():
        url = parts[0]
    return f"{url}/{db}"


def create_celery_app() -> Celery:
    """Build and configure the Celery application from :data:`ACTIVE_TOPICS`."""
    settings = get_settings()
    base = settings.DATABASE_REDIS_URL

    # Derive worker module paths from active topic task_paths.
    _include = list({
        ".".join(t.task_path.rsplit(".", 1)[:-1])
        for t in ACTIVE_TOPICS
        if t.task_path
    })

    app = Celery(
        "fin_streaming",
        broker=_broker_url(base, db=CELERY_BROKER_DB),
        backend=_broker_url(base, db=CELERY_BACKEND_DB),
        include=_include,
    )

    # Build beat schedule from active topics
    _beat_schedule = {
        f"poll-{topic.human_key}": {
            "task": topic.task_path,
            "schedule": topic.beat_interval,
        }
        for topic in ACTIVE_TOPICS
        if topic.task_path
    }

    app.conf.update(**CELERY_WORKER_CONFIG, beat_schedule=_beat_schedule)

    return app


celery_app: Celery = create_celery_app()
