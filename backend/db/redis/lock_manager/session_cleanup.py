"""Canonical cleanup for all Redis keys owned by a LangGraph thread session.

Every query (``thread_id``) writes to several Redis key spaces during its
lifetime.  Without coordinated cleanup, stale keys accumulate and can cause
incorrect behaviour on re-connection (e.g. watch-registry pointing at old
task IDs, stale pending-notify entries re-delivering after session end).

Thread-scoped key inventory
---------------------------
Key pattern                              Module                     Normal cleanup path
---------------------------------------  -------------------------  ----------------------------------------
``tokens:<thread_id>``                   publisher                  ``delete_stream`` in ``emit_done``
``fin:query:phase:<thread_id>``          query_phase                ``delete_query_phase`` in runner/cancel
``notify_pending:<thread_id>``           publisher                  ``clear_pending_notify`` in SSE teardown (*not* cleaned here)
``watch:<thread_id>``                    watch_registry             ``unregister_watch`` in SSE teardown
``task_active:<thread_id>``              api.registry               ``clear_task_active`` in runner/cancel
``task_ack:<thread_id>``                 task_ack_store             (TTL=3600s; also cleaned here)
``fin:perf:<thread_id>``                 perf_test celery_ingest    (no TTL; only cleaned here)
``fin:perf:ingest:state:<thread_id>``    perf_test celery_ingest    (no TTL; only cleaned here)

``notify_pending`` is intentionally excluded from this cleanup because it is
the drain-cycle recovery store for lost lifecycle events (including ``done``).
If the runner deleted it immediately after ``emit_done``, any ``done`` event
that was dropped in the Pub/Sub path could never be recovered — the SSE
generator's 25-second drain cycle would find an empty hash and yield only a
ping, leaving the browser in a permanent loading state.  The hash carries its
own TTL (~19 min) and is explicitly cleared by ``clear_pending_notify`` in the
SSE ``finally`` block when the client session closes cleanly.

Note: ``lifecycle:{thread_id}`` and ``cancel:{thread_id}`` are Redis Pub/Sub
channel names, not persistent keys — no cleanup needed.

Note: ``fin:perf:*`` keys are only written for perf-test sessions; the DEL
on a non-existent key is a cheap no-op, so these are included unconditionally.

This module provides :func:`cleanup_thread_session` which deletes **all** of
the above in one atomic pipeline call so runner, cancel-endpoint, and error
paths share a single canonical cleanup rather than per-module deletions.

Usage
-----
::

    # At the end of run_graph_async (all exit paths: completed / cancelled / error)
    from backend.db.redis.lock_manager import cleanup_thread_session
    await cleanup_thread_session(thread_id)
"""

from __future__ import annotations

import logging

from backend.db.redis.streams.publisher import (
    stream_key,
)
from backend.db.redis.session.query_phase import _phase_key
from backend.db.redis.router import get_redis_router
from backend.db.redis.session.task_ack_store import _task_ack_key
from backend.db.redis.session.watch_registry import _watch_key, _local_cache as _watch_local_cache

logger = logging.getLogger(__name__)

# Matches api.registry._TASK_ACTIVE_PREFIX
_TASK_ACTIVE_PREFIX = "task_active:"

# Perf-test stream key prefixes — mirrors constants in
# backend.graph.agents.perf_test.celery_ingest.config to avoid a cross-layer
# import. DEL on a non-existent key is a no-op, so these are included
# unconditionally for every session.
_PERF_STREAM_PREFIX = "fin:perf"
_PERF_STATE_KEY_PREFIX = "fin:perf:ingest:state"


def _task_active_key(thread_id: str) -> str:
    """Return the Redis key for the task-active flag of *thread_id*."""
    return f"{_TASK_ACTIVE_PREFIX}{thread_id}"


def _perf_stream_key(thread_id: str) -> str:
    """Return the perf-test token stream key for *thread_id*."""
    return f"{_PERF_STREAM_PREFIX}:{thread_id}"


def _perf_state_key(thread_id: str) -> str:
    """Return the perf-test ingest state hash key for *thread_id*."""
    return f"{_PERF_STATE_KEY_PREFIX}:{thread_id}"


async def cleanup_thread_session(thread_id: str) -> None:
    """Delete all Redis keys owned by *thread_id* in a single pipeline.

    Covers:
    * ``tokens:<thread_id>``                  — Redis Stream (LLM tokens)
    * ``fin:query:phase:<thread_id>``         — ephemeral query-phase label
    * ``watch:<thread_id>``                   — SSE watch registry
    * ``task_active:<thread_id>``             — cross-instance task-active flag
    * ``task_ack:<thread_id>``                — SSE task-delivery ACK tracking hash
    * ``fin:perf:<thread_id>``                — perf-test token stream (no-op for regular queries)
    * ``fin:perf:ingest:state:<thread_id>``   — perf-test ingest state hash (no-op for regular queries)

    **Not covered** (intentional):
    * ``notify_pending:<thread_id>`` — this is the drain-cycle recovery store.
      Deleting it here would destroy the fallback that recovers ``done`` (and
      other lifecycle events) when Redis Pub/Sub delivery is interrupted.  The
      hash carries its own TTL (~19 min) and is explicitly cleared by
      ``clear_pending_notify`` in the SSE ``finally`` block.

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
        # notify_pending:{thread_id} intentionally excluded — see module docstring.
        _watch_key(thread_id),
        _task_active_key(thread_id),
        _task_ack_key(thread_id),
        # Perf-test keys — no-op DEL for regular (non-perf) sessions.
        _perf_stream_key(thread_id),
        _perf_state_key(thread_id),
    ]

    try:
        # All keys for this thread_id hash to the same shard — use a single pipeline.
        client = get_redis_router().get_client_for_thread(thread_id)
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
        client = get_redis_router().get_client_for_thread(thread_id)
        for key in keys:
            try:
                await client.delete(key)
            except Exception as key_exc:  # noqa: BLE001
                logger.warning(
                    "[session_cleanup] delete_error key=%s thread_id=%s: %s",
                    key,
                    thread_id,
                    key_exc,
                )


async def purge_stale_perf_streams() -> None:
    """Delete all leftover ``fin:perf:*`` keys across every Redis shard.

    Perf-test token streams and ingest-state hashes carry no TTL — they are
    intentionally deleted by :func:`cleanup_thread_session` at the end of each
    session.  If the server was terminated mid-test those keys are orphaned and
    will remain in Redis indefinitely, consuming large amounts of memory (each
    100 k-token stream can occupy ≈ 1–2 MB).

    This function is called once during FastAPI startup so that a fresh process
    always starts with a clean slate.  It is safe to call concurrently with
    other startup tasks because no active perf sessions can exist before the
    server finishes initialisation.

    Scans all shards in the :class:`~backend.db.redis.router.RedisRouter` using
    ``SCAN … MATCH fin:perf:*`` with a batch size of 500 and deletes every
    matching key in pipelines of 500.

    Also purges stale ``watch:*`` keys left by sessions that disconnected before
    their SSE generator could call ``unregister_watch``.
    """
    router = get_redis_router()
    total_deleted = 0
    _BATCH = 500
    _PATTERNS = ("fin:perf:*", "watch:*")

    for shard_idx in range(router.node_count):
        client = router.get_client_at(shard_idx)
        for pattern in _PATTERNS:
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=_BATCH)
                if keys:
                    pipe = client.pipeline(transaction=False)
                    for key in keys:
                        pipe.delete(key)
                    results = await pipe.execute()
                    total_deleted += sum(1 for r in results if r)
                if cursor == 0:
                    break

    logger.info("[session_cleanup] purge_stale_perf_streams deleted=%d", total_deleted)


__all__ = ["cleanup_thread_session", "purge_stale_perf_streams"]
