"""backend.main_thread.startup -- recover running threads on FastAPI startup.

On startup, queries PostgreSQL for threads that still have ``status='running'``
and dispatches a recovery graph run for each one that either:

* Has no Redis ownership lock (lock expired during downtime), or
* Has a lock pointing to a dead instance (previous process died).

Threads whose lock points to another *live* instance are skipped -- that
instance is already handling them.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def recover_running_threads() -> None:
    """Find orphaned running threads and re-dispatch them for recovery.

    Called once from the FastAPI lifespan after DB pools and the compiled
    graph are initialised.  Errors per thread are logged but never raised
    so that the remaining threads can be processed.
    """
    from backend.db.postgres import raw_conn
    from backend.db.redis.session import set_thread_user, set_viewer
    from backend.main_thread.errors import MAIN_THREAD_RECOVERY_FAILED
    from backend.main_thread.executor import ThreadRoutingError, dispatch_graph_run
    from backend.main_thread.lock import check_owner_alive, get_lock_owner, this_owner

    this = this_owner()

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT uq.thread_id, uq.query, uq.user_id::text AS user_id
            FROM fin_agents.user_queries uq
            WHERE uq.status = 'running'
              AND EXISTS (
                  SELECT 1
                  FROM fin_agents.nodes n
                  WHERE n.thread_id = uq.thread_id
                    AND n.status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
                    AND n.is_last_paused_by_server = TRUE
              )
            """
        )
        rows = await cur.fetchall()

    if not rows:
        return

    logger.warning(
        "[main_thread.startup] found %d running thread(s) to evaluate for recovery",
        len(rows),
    )

    for row in rows:
        thread_id: str = row["thread_id"]
        query: str = row["query"]
        user_id: str = row["user_id"]

        owner = await get_lock_owner(thread_id)

        if owner is not None:
            is_mine = (
                owner.get("port") == this["port"]
                and owner.get("pid") == this["pid"]
            )
            if not is_mine:
                alive = await check_owner_alive(owner)
                if alive:
                    # Another live instance owns this -- it will handle it.
                    continue
                # Owner is dead -- fall through to dispatch recovery.

        try:
            # Refresh the viewer flags so stream_core sees a live viewer during
            # recovery.  The flags may have expired (30 min TTL) or been cleared
            # by the frontend before the restart.  Setting them here mirrors what
            # submit_query does for new queries and prevents tokens from being
            # silently discarded when viewers_present evaluates to False.
            await set_thread_user(thread_id, user_id)
            await set_viewer(user_id, thread_id)
            await dispatch_graph_run(thread_id, query, resume=True)
            logger.error(
                "[main_thread.startup] dispatched recovery thread_id=%s", thread_id
            )
        except ThreadRoutingError:
            # Another instance grabbed the lock between our check and dispatch -- fine.
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[main_thread.startup] %s thread_id=%s: %s",
                MAIN_THREAD_RECOVERY_FAILED, thread_id, exc,
            )


async def cleanup_stale_celery_tasks() -> None:
    """Revoke all Celery tasks still running from a previous process and purge queues.

    Must be called before :func:`recover_running_threads` so that zombie
    workers from the previous process are killed before the graph re-dispatches
    fresh Celery tasks for recovered threads.

    Strategy
    --------
    1. Inspect every connected worker for *active* (running) tasks and revoke
       each one with ``terminate=True``.  This sends SIGTERM to the worker
       process handling the task.
    2. Purge the Celery queues (remove *pending* tasks that were queued by the
       old process but not yet picked up by a worker).  Step 2 is protected by
       a Redis distributed lock (``fin:startup:celery:purge``, 60 s TTL) so
       that only **one** FastAPI instance calls ``control.purge()`` per restart
       cycle.  Without this guard, a second instance starting slightly later
       would purge tasks that the first instance already re-dispatched during
       :func:`recover_running_threads`, leaving the Celery task permanently
       PENDING and causing the 30-second task_delegation warning.

    The inspect call is synchronous and blocking so it runs in a thread-pool
    executor.  A 5-second timeout prevents startup from hanging if workers are
    temporarily unreachable.
    """
    import asyncio
    from backend.celery_task.celery_engine import celery_engine
    from backend.db.redis.client import get_client

    def _do_revoke() -> int:
        """Revoke all currently active Celery tasks.  Returns revoked count."""
        try:
            active_by_worker = celery_engine.control.inspect(timeout=5).active() or {}
        except Exception:  # noqa: BLE001
            active_by_worker = {}

        revoked = 0
        for _worker, tasks in active_by_worker.items():
            for task_info in tasks:
                celery_task_id = task_info.get("id")
                if celery_task_id:
                    try:
                        celery_engine.control.revoke(celery_task_id, terminate=True)
                        revoked += 1
                    except Exception:  # noqa: BLE001
                        pass
        return revoked

    def _do_purge() -> int:
        """Purge pending tasks from all Celery queues.  Returns purged count."""
        try:
            return celery_engine.control.purge() or 0
        except Exception:  # noqa: BLE001
            return 0

    revoked = await asyncio.to_thread(_do_revoke)

    # Only one FastAPI instance should purge per restart cycle.  A second
    # instance racing through startup could purge tasks just dispatched by the
    # first instance's recover_running_threads(), pinning those tasks as PENDING
    # indefinitely.  Use a Redis SET NX lock (60 s TTL) so the winner runs
    # control.purge() and losers skip it safely.
    _PURGE_LOCK_KEY = "fin:startup:celery:purge"
    _PURGE_LOCK_TTL = 60
    purged = 0
    try:
        redis = await get_client(shard=0)
        acquired = await redis.set(_PURGE_LOCK_KEY, "1", nx=True, ex=_PURGE_LOCK_TTL)
        if acquired:
            purged = await asyncio.to_thread(_do_purge)
    except Exception:  # noqa: BLE001
        pass

    if revoked or purged:
        logger.warning(
            "[main_thread.startup] cleanup: revoked %d active Celery task(s),"
            " purged %d pending task(s) from previous process",
            revoked,
            purged,
        )


__all__ = ["recover_running_threads", "cleanup_stale_celery_tasks"]
