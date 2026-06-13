"""Celery application for Redis Streams background workers.

Workers batch-consume each Redis Stream topic via consumer groups.  The beat
scheduler re-enqueues polling tasks at a fixed interval.

Broker: ``DATABASE_REDIS_URL`` DB 1 -- Backend: ``DATABASE_REDIS_URL`` DB 2
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab  # noqa: F401 -- available for callers
from celery.signals import after_setup_logger, after_setup_task_logger, worker_init

from backend.config import get_settings
from backend.celery_task.config import (
    ACTIVE_TOPICS,
    CELERY_BACKEND_DB,
    CELERY_BROKER_DB,
    CELERY_WORKER_CONFIG,
)
from backend.celery_task.log_filters import CeleryTaskSummaryFilter

# One shared filter instance per process -- keeps counts consistent across
# the celery logger and the task logger.
_task_summary_filter = CeleryTaskSummaryFilter()


@worker_init.connect
def _configure_worker_logging(**kwargs) -> None:  # type: ignore[misc]
    """Apply the project-wide logging configuration in the worker subprocess.

    Called once when the Celery worker process starts, before any task is
    executed.  After dictConfig runs we attach ``_task_summary_filter``
    programmatically to the ``celery_console`` handler (the StreamHandler on
    stdout that belongs to the ``celery`` logger) rather than declaring it as a
    ``()`` factory string inside dictConfig, which fails under Python 3.12 when
    Celery has already initialised its own logging subsystem.
    """
    import sys
    import logging as _logging
    from backend.log_config import configure_logging
    configure_logging()
    # Attach the shared filter instance to every stdout StreamHandler on the
    # celery logger (i.e. celery_console).  File handlers are intentionally
    # left unfiltered so streaming.log captures all Celery task records.
    celery_logger = _logging.getLogger("celery")
    for handler in celery_logger.handlers:
        if isinstance(handler, _logging.StreamHandler) and getattr(handler, "stream", None) is sys.stdout:
            handler.addFilter(_task_summary_filter)


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


def create_celery_engine() -> Celery:
    """Build and configure the Celery application from :data:`ACTIVE_TOPICS`.

    The Celery **broker** and **backend** are pinned to shard 0 of the Redis
    cluster -- this is a Celery infrastructure constraint (the broker URL is
    set once at process start and cannot vary per task).

    On-demand tasks that carry a ``thread_id`` (completion and stream workers)
    are dispatched to a named queue determined by
    ``SHA-256(thread_id) % n_shards`` via :func:`~backend.celery_task.config.get_ondemand_queue`
    so that work for the same session consistently lands on the same worker.
    When ``DATABASE_REDIS_NODES`` is not set, ``n_shards`` is 1 and all tasks
    go to ``celery_ondemand_0``, making single-instance deployments work
    without any configuration change.
    """
    settings = get_settings()

    # Broker/backend are pinned to shard 0 -- Celery infrastructure constraint.
    # On-demand task routing by thread_id is handled in task_delegation.py via
    # get_ondemand_queue(thread_id), which selects from celery_ondemand_{0..n}.
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
        "backend.celery_task.workers.tasks.completion_task",
        "backend.celery_task.workers.tasks.stream_task",
    ]
    for mod in _ONDEMAND_MODULES:
        if mod not in _include:
            _include.append(mod)

    celery_engine = Celery(
        "fin_streaming",
        broker=_broker_url(base, db=CELERY_BROKER_DB),
        backend=_broker_url(base, db=CELERY_BACKEND_DB),
        include=_include,
    )

    # Build beat schedule from active topics -- only include topics with a
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

    celery_engine.conf.update(**CELERY_WORKER_CONFIG, beat_schedule=_beat_schedule)

    return celery_engine


celery_engine: Celery = create_celery_engine()
