"""backend.main_thread.executor — in-process graph dispatch for main thread.

Replaces the standalone graph_runner process.  Each FastAPI (main thread)
instance runs graph coroutines directly on uvicorn's asyncio event loop as
background asyncio.Tasks.

Thread ownership
----------------
Before dispatching a graph, the executor acquires a Redis ownership lock
(``fin:thread:lock:{thread_id}``) so that exactly one main thread instance
owns each graph run.  The lock is renewed periodically while the graph runs
and released on completion.

Routing logic (``dispatch_graph_run``)
---------------------------------------
1. No lock exists → acquire it, dispatch.
2. Lock is owned by **this** instance, task already running → idempotent no-op.
3. Lock is owned by **this** instance, task not running → re-dispatch (recovery).
4. Lock owned by **another** instance that is **alive** → raise
   :exc:`ThreadRoutingError`; caller returns HTTP 503 so nginx can retry on the
   correct instance.
5. Lock owned by **another** instance that is **dead** → steal lock, dispatch.

The caller is responsible for handling :exc:`ThreadRoutingError` and
translating it to an appropriate HTTP response.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

_FORK_PREFIX = "__fork__:"


class ThreadRoutingError(Exception):
    """Raised when a thread is actively owned by another live main thread.

    The caller should return HTTP 503 with a ``Retry-After`` header so the
    client can retry and nginx's consistent-hash routing will land on the
    correct instance.
    """

    def __init__(self, owner_port: int) -> None:
        self.owner_port = owner_port
        super().__init__(
            f"Thread owned by live main thread on port {owner_port}; retry the request"
        )


async def _renew_lock_loop(thread_id: str, stop_event: asyncio.Event) -> None:
    """Background task: renew the thread lock until *stop_event* is set.

    Args:
        thread_id:  LangGraph thread UUID.
        stop_event: Signal to stop renewing (set when graph finishes).
    """
    from backend.config import get_settings
    from backend.main_thread.lock import renew_lock

    interval = get_settings().THREAD_LOCK_RENEW_INTERVAL_SECONDS
    while not stop_event.is_set():
        try:
            await asyncio.sleep(interval)
            if stop_event.is_set():
                break
            if not await renew_lock(thread_id):
                logger.error(
                    "[main_thread.executor] lock renewal failed thread_id=%s — ownership lost",
                    thread_id,
                )
                # Graph continues; another instance may attempt a steal, but the
                # running graph will still complete and release on finish.
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[main_thread.executor] lock renewal error thread_id=%s: %s",
                thread_id, exc,
            )


async def _run_graph(thread_id: str, query: str, *, resume: bool = False) -> None:
    """Execute or resume the LangGraph for *thread_id* with lock lifecycle.

    Runs as an asyncio.Task on uvicorn's event loop.  Renews the Redis
    ownership lock in a background sub-task and releases it on exit.

    Args:
        thread_id: LangGraph thread UUID.
        query:     Raw query string, ``__fork__:<json>`` for fork-resume,
                   or irrelevant when *resume* is ``True``.
        resume:    If ``True``, invoke with ``input=None`` to replay from
                   the last LangGraph checkpoint (crash recovery).
    """
    from backend.db.postgres import raw_conn
    from backend.langgraph.compiled import get_compiled_graph
    from backend.langgraph.lifecycle import complete_thread, register_thread
    from backend.main_thread.cancel_flag import clear_cancel_flag
    from backend.main_thread.lock import release_lock

    stop_renew = asyncio.Event()
    renew_task = asyncio.create_task(
        _renew_lock_loop(thread_id, stop_renew),
        name=f"lock-renew-{thread_id}",
    )

    register_thread(thread_id)
    try:
        graph = get_compiled_graph()

        if resume:
            # Crash / failover recovery: replay from last checkpoint.
            config = {"configurable": {"thread_id": thread_id}}
            await graph.ainvoke(None, config=config)

        elif query.startswith(_FORK_PREFIX):
            # Fork / re-explore: embedded fork_config in query field.
            fork_config = json.loads(query[len(_FORK_PREFIX):])
            await graph.ainvoke(None, config=fork_config)

        else:
            # Normal fresh run: transition status → running, then invoke.
            async with raw_conn() as conn:
                await conn.execute(
                    "UPDATE fin_agents.user_queries "
                    "SET status = 'running' "
                    "WHERE thread_id = %s AND status = 'received'",
                    (thread_id,),
                )
            config = {"configurable": {"thread_id": thread_id}}
            initial_state = {"thread_id": thread_id, "query": query}
            await graph.ainvoke(initial_state, config=config)

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[main_thread.executor] graph failed thread_id=%s: %s", thread_id, exc
        )
        try:
            await complete_thread(thread_id, failed=True, error=str(exc))
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.error(
                "[main_thread.executor] complete_thread failed thread_id=%s: %s",
                thread_id, cleanup_exc,
            )
    finally:
        stop_renew.set()
        renew_task.cancel()
        try:
            await renew_task
        except asyncio.CancelledError:
            pass
        await clear_cancel_flag(thread_id)
        await release_lock(thread_id)


async def dispatch_graph_run(
    thread_id: str,
    query: str,
    *,
    resume: bool = False,
) -> None:
    """Acquire thread ownership lock and dispatch graph execution as asyncio.Task.

    Implements the full routing / ownership check:

    1. No lock → acquire → dispatch.
    2. Lock owned by this instance, task running → idempotent no-op.
    3. Lock owned by this instance, task not running → re-dispatch.
    4. Lock owned by live foreign instance → raise :exc:`ThreadRoutingError`.
    5. Lock owned by dead foreign instance → steal lock → dispatch.

    Args:
        thread_id: LangGraph thread UUID.
        query:     Raw query string (or fork-prefixed string).
        resume:    If ``True``, resume from the last LangGraph checkpoint.

    Raises:
        ThreadRoutingError: If the thread is owned by another live instance.
    """
    from backend.main_thread.errors import (
        MAIN_THREAD_LOCK_CONFLICT,
        MAIN_THREAD_LOCK_STOLEN,
    )
    from backend.main_thread.lock import (
        acquire_lock,
        check_owner_alive,
        get_lock_owner,
        steal_lock,
        this_owner,
    )
    from backend.main_thread.registry import is_running, register

    owner_info = this_owner()
    existing_owner = await get_lock_owner(thread_id)

    if existing_owner is not None:
        is_mine = (
            existing_owner.get("port") == owner_info["port"]
            and existing_owner.get("pid") == owner_info["pid"]
        )
        if is_mine:
            if is_running(thread_id):
                # Already running on this instance — idempotent.
                return
            # Lock is ours but task finished/crashed — re-dispatch below.
        else:
            # Lock belongs to a different instance.
            alive = await check_owner_alive(existing_owner)
            if alive:
                logger.error(
                    "[main_thread.executor] %s thread_id=%s owner_port=%d",
                    MAIN_THREAD_LOCK_CONFLICT, thread_id, existing_owner.get("port"),
                )
                raise ThreadRoutingError(existing_owner["port"])
            # Owner is dead — steal the lock.
            logger.error(
                "[main_thread.executor] %s thread_id=%s dead_port=%d",
                MAIN_THREAD_LOCK_STOLEN, thread_id, existing_owner.get("port"),
            )
            await steal_lock(thread_id)
    else:
        # No lock — try to acquire (handles concurrent races via SET NX).
        acquired = await acquire_lock(thread_id)
        if not acquired:
            # Race: another instance just acquired it.
            existing_owner = await get_lock_owner(thread_id)
            if existing_owner is not None:
                alive = await check_owner_alive(existing_owner)
                if alive:
                    raise ThreadRoutingError(existing_owner["port"])
                # Dead already — steal it.
                await steal_lock(thread_id)
            # Lock vanished between NX fail and GET (extremely rare) — proceed.

    task = asyncio.create_task(
        _run_graph(thread_id, query, resume=resume),
        name=f"graph-{thread_id}",
    )
    register(thread_id, task)


__all__ = ["ThreadRoutingError", "dispatch_graph_run"]
