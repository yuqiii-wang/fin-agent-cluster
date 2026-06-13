"""Thread-level in-process registry.

Holds one ``asyncio.Event`` (cancel token) per active thread and tracks
the Celery ``AsyncResult`` for every in-flight task so they can be revoked
during thread or node cancellation.

This module is intentionally a **process-local singleton** -- it has no Redis
or DB dependency.  State is lost on process restart, which is acceptable
because the DB is the source of truth; the registry only accelerates
in-process signal delivery.

Thread safety
-------------
All mutations go through ``asyncio.Lock`` guards because FastAPI and
LangGraph share the same event loop; there is no multi-threading concern
here beyond the lock.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.db.postgres.lifecycle_status import TERMINAL_QUERY_STATUSES, TERMINAL_WORK_STATUSES

logger = logging.getLogger(__name__)


class ThreadRegistry:
    """Process-local registry for thread cancel tokens and Celery result handles.

    Lifecycle
    ---------
    1. ``register_thread`` is called by the thread start path; returns the
       cancel token (asyncio.Event) for the caller to poll in task delegation.
    2. ``register_celery_result`` is called immediately after each Celery
       ``send_task`` so the result can be revoked on cancellation.
    3. ``set_cancelled`` sets the cancel event, causing all delegation polls
       to detect the signal on their next iteration.
    4. ``cleanup_thread`` is called once a thread reaches a terminal state
       to release memory held by the token and any dangling Celery handles.
    """

    def __init__(self) -> None:
        self._cancel_tokens: dict[str, asyncio.Event] = {}
        # Maps task_id -> Celery AsyncResult for all in-flight tasks.
        self._celery_results: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Thread-level helpers
    # ------------------------------------------------------------------

    def register_thread(self, thread_id: str) -> asyncio.Event:
        """Create and store a cancel token for *thread_id*.

        If a token already exists (re-registration on retry), the existing
        token is returned unchanged so poll loops do not miss signals set
        between calls.

        Args:
            thread_id: LangGraph thread UUID.

        Returns:
            The ``asyncio.Event`` cancel token for this thread.
        """
        if thread_id not in self._cancel_tokens:
            self._cancel_tokens[thread_id] = asyncio.Event()
        return self._cancel_tokens[thread_id]

    def get_cancel_token(self, thread_id: str) -> asyncio.Event | None:
        """Return the cancel token for *thread_id*, or ``None`` if not registered."""
        return self._cancel_tokens.get(thread_id)

    def is_cancelled(self, thread_id: str) -> bool:
        """Return ``True`` if the cancel token for *thread_id* has been set."""
        token = self._cancel_tokens.get(thread_id)
        return token.is_set() if token is not None else False

    def set_cancelled(self, thread_id: str) -> None:
        """Set the cancel token for *thread_id*, signalling all pollers."""
        token = self._cancel_tokens.get(thread_id)
        if token is not None:
            token.set()

    def cleanup_thread(self, thread_id: str) -> None:
        """Release the cancel token for *thread_id*.

        Does **not** revoke dangling Celery results -- callers should revoke
        before cleanup, or let the results expire naturally.
        """
        self._cancel_tokens.pop(thread_id, None)

    # ------------------------------------------------------------------
    # All registered thread IDs (for shutdown)
    # ------------------------------------------------------------------

    def active_thread_ids(self) -> list[str]:
        """Return all thread IDs currently in the registry."""
        return list(self._cancel_tokens.keys())

    # ------------------------------------------------------------------
    # Celery result tracking
    # ------------------------------------------------------------------

    def register_celery_result(self, task_id: str, result: Any) -> None:
        """Store a Celery ``AsyncResult`` keyed by *task_id*.

        Args:
            task_id: Governance UUID from ``make_task_id()``.
            result:  Celery ``AsyncResult`` returned by ``send_task``.
        """
        self._celery_results[task_id] = result

    def revoke_celery_task(self, task_id: str) -> None:
        """Revoke and discard the Celery result for *task_id*.

        Uses ``terminate=True`` so an already-running worker process receives
        SIGTERM.  Errors are swallowed -- revocation is best-effort.

        Args:
            task_id: Governance UUID to revoke.
        """
        result = self._celery_results.pop(task_id, None)
        if result is None:
            return
        try:
            result.revoke(terminate=True, signal="SIGTERM")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lifecycle] revoke failed task_id=%s: %s", task_id, exc)

    def revoke_all_celery_tasks(self) -> None:
        """Revoke every tracked Celery result (used during process shutdown)."""
        task_ids = list(self._celery_results.keys())
        for task_id in task_ids:
            self.revoke_celery_task(task_id)

    def get_celery_result(self, task_id: str) -> Any | None:
        """Return the Celery AsyncResult for *task_id*, or ``None`` if not registered.

        Used by retry-fresh to poll whether the old worker has finished
        (result is discarded by ``discard_celery_result`` in ``_await_result``).

        Args:
            task_id: Governance UUID of the task.
        """
        return self._celery_results.get(task_id)

    def discard_celery_result(self, task_id: str) -> None:
        """Remove a completed Celery result from the registry without revoking."""
        self._celery_results.pop(task_id, None)


# ---------------------------------------------------------------------------
# Process-local singleton
# ---------------------------------------------------------------------------

_registry = ThreadRegistry()


def get_thread_registry() -> ThreadRegistry:
    """Return the process-local :class:`ThreadRegistry` singleton."""
    return _registry


__all__ = [
    "ThreadRegistry",
    "get_thread_registry",
    "get_celery_result",
    "TERMINAL_WORK_STATUSES",
    "TERMINAL_QUERY_STATUSES",
]
