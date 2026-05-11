"""backend.main_thread.startup — recover running threads on FastAPI startup.

On startup, queries PostgreSQL for threads that still have ``status='running'``
and dispatches a recovery graph run for each one that either:

* Has no Redis ownership lock (lock expired during downtime), or
* Has a lock pointing to a dead instance (previous process died).

Threads whose lock points to another *live* instance are skipped — that
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
    from backend.main_thread.errors import MAIN_THREAD_RECOVERY_FAILED
    from backend.main_thread.executor import ThreadRoutingError, dispatch_graph_run
    from backend.main_thread.lock import check_owner_alive, get_lock_owner, this_owner

    this = this_owner()

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT thread_id, query FROM fin_agents.user_queries WHERE status = 'running'"
        )
        rows = await cur.fetchall()

    if not rows:
        return

    logger.error(
        "[main_thread.startup] found %d running thread(s) to evaluate for recovery",
        len(rows),
    )

    for row in rows:
        thread_id: str = row["thread_id"]
        query: str = row["query"]

        owner = await get_lock_owner(thread_id)

        if owner is not None:
            is_mine = (
                owner.get("port") == this["port"]
                and owner.get("pid") == this["pid"]
            )
            if not is_mine:
                alive = await check_owner_alive(owner)
                if alive:
                    # Another live instance owns this — it will handle it.
                    continue
                # Owner is dead — fall through to dispatch recovery.

        try:
            await dispatch_graph_run(thread_id, query, resume=True)
            logger.error(
                "[main_thread.startup] dispatched recovery thread_id=%s", thread_id
            )
        except ThreadRoutingError:
            # Another instance grabbed the lock between our check and dispatch — fine.
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[main_thread.startup] %s thread_id=%s: %s",
                MAIN_THREAD_RECOVERY_FAILED, thread_id, exc,
            )


__all__ = ["recover_running_threads"]
