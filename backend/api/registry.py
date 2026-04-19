"""Shared in-process registry of active query background tasks.

Centralises the ``running_tasks`` dict so the query router (writer) and the
stream router (reader) can both access it without a circular import.

Task types
----------
- **asyncio.Task** — perf-test queries (``_run_perf_graph``), which run in the
  FastAPI event loop.
- **celery.result.AsyncResult** — real LangGraph queries dispatched to a Celery
  worker process via ``run_graph.delay()``.

The :func:`is_task_active` helper hides this distinction behind a single bool
check and does lazy GC: entries for completed tasks are removed on first check
so the dict does not grow unbounded.
"""

from __future__ import annotations

import asyncio
from typing import Any, Union

from celery.result import AsyncResult

# Maps thread_id → asyncio.Task (perf test) | Celery AsyncResult (graph query).
# Entries are added by the query endpoint and lazily removed by is_task_active().
running_tasks: dict[str, Union[asyncio.Task, AsyncResult]] = {}


def is_task_active(thread_id: str) -> bool:
    """Return ``True`` if *thread_id* has a live, not-yet-finished task.

    Performs lazy GC: when a completed/done entry is encountered it is removed
    from ``running_tasks`` before returning ``False``.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if the task exists and has not finished, ``False`` otherwise.
    """
    task: Any = running_tasks.get(thread_id)
    if task is None:
        return False
    if isinstance(task, asyncio.Task):
        if task.done():
            running_tasks.pop(thread_id, None)
            return False
        return True
    # Celery AsyncResult — .ready() is True for SUCCESS / FAILURE / REVOKED.
    if task.ready():
        running_tasks.pop(thread_id, None)
        return False
    return True
