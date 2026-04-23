"""Canonical cleanup for all Redis keys owned by a LangGraph thread session.

Every query (``thread_id``) writes to several Redis key spaces during its
lifetime.  Without coordinated cleanup, stale keys accumulate and can cause
incorrect behaviour on re-connection (e.g. watch-registry pointing at old
task IDs, stale pending-notify entries re-delivering after session end).

Thread-scoped key inventory
---------------------------
Key pattern                        Module                  Normal cleanup path
---------------------------------  ----------------------  -------------------
``tokens:<thread_id>``             publisher               ``delete_stream`` in ``emit_done``
``fin:query:phase:<thread_id>``    query_phase             ``delete_query_phase`` in runner/cancel
``notify_pending:<thread_id>``     publisher               ``clear_pending_notify`` in SSE teardown
``watch:<thread_id>``              watch_registry          ``unregister_watch`` in SSE teardown
``task_active:<thread_id>``        api.registry            ``clear_task_active`` in runner/cancel

Note: ``lifecycle:<thread_id>`` is a Redis Pub/Sub channel name, not a
persistent key — no cleanup needed.

This module provides :func:`cleanup_thread_session` which deletes **all** of
the above in one atomic pipeline call so runner, cancel-endpoint, and error
paths share a single canonical cleanup rather than per-module deletions.

Usage
-----
::

    # At the end of run_graph_async (all exit paths: completed / cancelled / error)
    from backend.db.redis.lock_manager.session_cleanup import cleanup_thread_session
    await cleanup_thread_session(thread_id)
"""

from __future__ import annotations

import logging

from backend.db.redis.publisher import (
    _get_publish_client,
    _pending_key,
    stream_key,
)
from backend.db.redis.query_phase import _phase_key
from backend.db.redis.watch_registry import _watch_key, _local_cache as _watch_local_cache

logger = logging.getLogger(__name__)

# Matches api.registry._TASK_ACTIVE_PREFIX
_TASK_ACTIVE_PREFIX = "task_active:"


def _task_active_key(thread_id: str) -> str:
    """Return the Redis key for the task-active flag of *thread_id*."""
    return f"{_TASK_ACTIVE_PREFIX}{thread_id}"


async def cleanup_thread_session(thread_id: str) -> None:
    """Delete all Redis keys owned by *thread_id* in a single pipeline.

    Covers:
    * ``tokens:<thread_id>``           — Redis Stream (LLM tokens)
    * ``fin:query:phase:<thread_id>``  — ephemeral query-phase label
    * ``notify_pending:<thread_id>``   — pg_notify pending-ack hash
    * ``watch:<thread_id>``            — SSE watch registry
    * ``task_active:<thread_id>``      — cross-instance task-active flag

    Also clears the in-process watch-registry cache entry.

    This is a best-effort call — individual key deletions failing do not abort
    the others.  All errors are logged as warnings.

    Args:
        thread_id: LangGraph UUID identifying the session to clean up.
    """
    # Clear in-process cache first (synchronous, cannot fail).
    _watch_local_cache.pop(thread_id, None)

    keys = [
        stream_key(thread_id),
        _phase_key(thread_id),
        _pending_key(thread_id),
        _watch_key(thread_id),
        _task_active_key(thread_id),
    ]

    try:
        client = await _get_publish_client()
        pipe = client.pipeline(transaction=False)
        for key in keys:
            pipe.delete(key)
        results = await pipe.execute()
        deleted = sum(1 for r in results if r)
        logger.info(
            "[session_cleanup] cleaned thread_id=%s keys_deleted=%d/%d",
            thread_id,
            deleted,
            len(keys),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[session_cleanup] pipeline failed thread_id=%s — falling back to individual deletes: %s",
            thread_id,
            exc,
        )
        # Best-effort individual deletes so a single Redis error does not
        # skip all remaining keys.
        for key in keys:
            try:
                client = await _get_publish_client()
                await client.delete(key)
            except Exception as key_exc:  # noqa: BLE001
                logger.warning(
                    "[session_cleanup] delete_error key=%s thread_id=%s: %s",
                    key,
                    thread_id,
                    key_exc,
                )


__all__ = ["cleanup_thread_session"]
