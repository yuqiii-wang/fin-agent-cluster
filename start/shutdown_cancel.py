"""Shutdown-time cancellation of active threads via DB + Centrifugo SSE."""
import asyncio
import logging


async def shutdown_cancel_all() -> None:
    """Cancel every active thread in the DB with SSE notifications.

    Runs in a fresh ``asyncio.run()`` event loop from the process-manager
    context (i.e. *not* inside a FastAPI instance).  Uses only the shared DB
    and Centrifugo connections that are reachable from the parent process.

    Errors are logged but never raised — shutdown must complete regardless.
    """
    _log = logging.getLogger("run.py.shutdown")
    try:
        from backend.db.postgres import raw_conn
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT thread_id FROM fin_agents.user_queries"
                " WHERE status NOT IN ('completed', 'failed', 'cancelled', 'wrong')"
            )
            rows = await cur.fetchall()
        thread_ids = [r["thread_id"] for r in rows]
    except Exception as exc:  # noqa: BLE001
        _log.error("[run.py] shutdown: failed to query active threads: %s", exc)
        return

    if not thread_ids:
        return

    print(f"[run.py] shutdown: cancelling {len(thread_ids)} active thread(s) with SSE …")
    from backend.langgraph.lifecycle.threads import cancel_thread
    for thread_id in thread_ids:
        try:
            await cancel_thread(thread_id, reason="shutdown")
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "[run.py] shutdown: cancel_thread failed thread_id=%s: %s",
                thread_id, exc,
            )


def run_shutdown_cancel() -> None:
    """Synchronous wrapper: runs :func:`shutdown_cancel_all` in a new loop."""
    try:
        asyncio.run(shutdown_cancel_all())
    except Exception as _exc:  # noqa: BLE001
        print(f"[run.py] shutdown cancel error: {_exc}")
