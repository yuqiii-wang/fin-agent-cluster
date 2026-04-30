"""Celery application for Redis Streams background workers.

Workers batch-consume each Redis Stream topic via consumer groups.  The beat
scheduler re-enqueues polling tasks at a fixed interval.

Broker: ``DATABASE_REDIS_URL`` DB 1 — Backend: ``DATABASE_REDIS_URL`` DB 2
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab  # noqa: F401 — available for callers
from celery.signals import after_setup_logger, after_setup_task_logger, worker_init

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


@worker_init.connect
def _configure_worker_logging(**kwargs) -> None:  # type: ignore[misc]
    """Apply the project-wide logging configuration in the worker subprocess.

    Called once when the Celery worker process starts, before any task is
    executed.  This ensures graph-runner and agent logs are routed to the
    correct log files (streaming.log, app.log) rather than stdout only.
    """
    from backend.log_config import configure_logging
    configure_logging()


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
    """Build and configure the Celery application from :data:`ACTIVE_TOPICS`.

    Celery broker and backend always use **shard 0** of the Redis cluster so
    task dispatch is isolated from application-level hash-routed data.  When
    ``DATABASE_REDIS_NODES`` is not set, shard 0 falls back to
    ``DATABASE_REDIS_URL``, making single-instance deployments work unchanged.
    """
    settings = get_settings()

    # Celery uses shard 0 exclusively — task queues are not key-sharded.
    from backend.db.redis.router import get_redis_router  # noqa: PLC0415
    base = get_redis_router().get_url_at(0)

    # Derive worker module paths from active topic task_paths.
    _include = list({
        ".".join(t.task_path.rsplit(".", 1)[:-1])
        for t in ACTIVE_TOPICS
        if t.task_path
    })

    # Always include on-demand workers that are not tied to a stream topic.
    _ONDEMAND_MODULES = [
        "backend.streaming.workers.throughput",
        "backend.streaming.workers.fanout",
    ]
    for mod in _ONDEMAND_MODULES:
        if mod not in _include:
            _include.append(mod)

    app = Celery(
        "fin_streaming",
        broker=_broker_url(base, db=CELERY_BROKER_DB),
        backend=_broker_url(base, db=CELERY_BACKEND_DB),
        include=_include,
    )

    # Build beat schedule from active topics — only include topics with a
    # beat_interval set (on-demand tasks like invoke_llm are excluded).
    _beat_schedule = {
        f"poll-{topic.human_key}": {
            "task": topic.task_path,
            "schedule": topic.beat_interval,
            "options": {"queue": topic.queue},
        }
        for topic in ACTIVE_TOPICS
        if topic.task_path and topic.beat_interval is not None
    }

    app.conf.update(**CELERY_WORKER_CONFIG, beat_schedule=_beat_schedule)

    return app


celery_app: Celery = create_celery_app()
