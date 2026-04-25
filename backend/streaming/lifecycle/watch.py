"""Streaming lifecycle — watch registry.

Thin re-export of the Redis-backed watch registry from
:mod:`backend.db.redis.session.watch_registry`.

Placing this here consolidates all streaming lifecycle symbols under a single
import path (``backend.streaming.lifecycle``) so callers do not need to reach
into the ``db.redis`` package directly.

Watch registry semantics
------------------------
The watch registry records which ``task_id`` the SSE client currently has
expanded.  The SSE generator uses this to suppress ``token`` events for tasks
the user has not opened (reducing browser noise during multi-task pipelines).

* ``register_watch(thread_id, task_id)`` — mark task as watched.
* ``unregister_watch(thread_id)`` — clear the watch on session close.
* ``get_watched_task(thread_id)`` — return the watched task_id or ``None``.
* ``is_thread_watching(thread_id)`` — predicate shorthand.

All calls are async and Redis-backed so ``PUT /stream/{id}/watch`` and
``GET /stream/{id}`` can be served by different FastAPI instances.
"""

from __future__ import annotations

from backend.db.redis.session.watch_registry import (
    get_watched_task,
    is_thread_watching,
    register_watch,
    unregister_watch,
)

__all__ = [
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
]
