"""backend.main_thread.executor -- in-process graph dispatch for main thread.

Replaces the standalone graph_runner process.  Each FastAPI (main thread)
instance runs graph coroutines directly on uvicorn's asyncio event loop as
background asyncio.Tasks.

Thread ownership
----------------
Before dispatching a graph, the executor acquires a Redis ownership lock
(``fin:thread:lock:{thread_id}``) so that exactly one main thread instance
owns each graph run.  The lock is renewed periodically while the graph runs
and released on completion.

Fix summary implemented here
-----------------------------
Fix 1 - CAS steal: ``steal_lock`` is CAS-based; if it returns ``None``
        (another instance already stole it), we route to the new owner.
Fix 2 - Zombie abort on renewal failure: when lock renewal fails in the
        background renew loop the running graph task is cancelled immediately
        via ``task.cancel()``.  ``_run_graph`` catches the resulting
        ``asyncio.CancelledError``, exits silently (does NOT mark the thread
        as failed), and proceeds to Fix 3 zombie cleanup.
Fix 3 - Zombie task cleanup: on zombie abort the ``finally`` block calls
        ``cleanup_zombie_tasks`` to mark all tasks created by this run
        (identified by their fencing token) as ``'wrong'``, so orphaned rows
        do not remain ``'running'`` indefinitely.
Fix 5 - Fencing token: the token returned by ``acquire_lock`` / ``steal_lock``
        is stored in a ``ContextVar`` (``backend.main_thread.context``) so all
        lifecycle write calls within the graph automatically stamp their DB rows
        with the token.  DB guards reject zombie writes with a lower token.

Routing logic (``dispatch_graph_run``)
---------------------------------------
1. No lock exists -> acquire it (returns fencing token) -> dispatch.
2. Lock is owned by **this** instance, task already running -> idempotent no-op.
3. Lock is owned by **this** instance, task not running -> re-dispatch with
   existing token (no new increment needed).
4. Lock owned by **another** instance that is **alive** -> raise
   :exc:`ThreadRoutingError`; caller returns HTTP 503 so nginx can retry on the
   correct instance.
5. Lock owned by **another** instance that is **dead** -> CAS steal lock
   (returns new fencing token) -> dispatch; if CAS fails (stolen by a third
   instance), route to that new owner instead.
"""

from __future__ import annotations

import asyncio
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


async def _renew_lock_loop(
    thread_id: str,
    stop_event: asyncio.Event,
    lock_lost_event: asyncio.Event,
) -> None:
    """Background task: renew the thread lock until *stop_event* is set.

    Fix 2 - If renewal fails (lock lost or expired), sets *lock_lost_event*
    and cancels the running graph task so the zombie run aborts promptly
    without proceeding to further node/task writes.

    Args:
        thread_id:       LangGraph thread UUID.
        stop_event:      Signal to stop renewing (set when graph finishes).
        lock_lost_event: Set before cancelling the graph task when the lock
                         is confirmed lost; ``_run_graph`` checks this to
                         distinguish a lock-loss abort from other cancellations.
    """
    from backend.config import get_settings
    from backend.main_thread.lock import renew_lock
    from backend.main_thread.registry import get_task

    interval = get_settings().THREAD_LOCK_RENEW_INTERVAL_SECONDS
    while not stop_event.is_set():
        try:
            await asyncio.sleep(interval)
            if stop_event.is_set():
                break
            if not await renew_lock(thread_id):
                logger.error(
                    "[main_thread.executor] lock renewal failed thread_id=%s -- "
                    "ownership lost; aborting zombie graph run",
                    thread_id,
                )
                lock_lost_event.set()
                task = get_task(thread_id)
                if task is not None and not task.done():
                    task.cancel()
                break
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[main_thread.executor] lock renewal error thread_id=%s: %s",
                thread_id, exc,
            )


async def _run_graph(
    thread_id: str,
    query: str,
    *,
    resume: bool = False,
    fencing_token: int = 0,
) -> None:
    """Execute or resume the LangGraph for *thread_id* with full lock lifecycle.

    Runs as an asyncio.Task on uvicorn's event loop.  Renews the Redis
    ownership lock in a background sub-task and releases it on exit.

    Fencing token is written to the ContextVar so all lifecycle DB writes
    within this coroutine (and any sub-coroutines) carry the token.

    Fix 2 - ``asyncio.CancelledError`` caused by lock-loss is caught and
    handled silently; the thread is NOT marked failed so the new owner can
    complete it from the last LangGraph checkpoint.

    Fix 3 - On zombie abort (lock_lost_event is set), ``cleanup_zombie_tasks``
    marks all tasks created during this run as ``'wrong'``.

    Args:
        thread_id:     LangGraph thread UUID.
        query:         Raw query string, ``__fork__:<json>`` for fork-resume,
                       or irrelevant when *resume* is ``True``.
        resume:        If ``True``, invoke with ``input=None`` to replay from
                       the last LangGraph checkpoint (crash recovery).
        fencing_token: Monotonic lock generation counter; stamped on all DB
                       writes within this run.
    """
    from typing import Any
    from backend.db.postgres import raw_conn, recover_graph_state_from_db
    from backend.langgraph.compiled import get_compiled_graph
    from backend.langgraph.lifecycle import complete_thread, register_thread
    from backend.langgraph.lifecycle.cancel_flag import clear_cancel_flag
    from backend.main_thread.context import set_fencing_token
    from backend.main_thread.errors import MAIN_THREAD_LOCK_LOST
    from backend.main_thread.lock import release_lock

    # Stamp the fencing token into the ContextVar; all async lifecycle write
    # calls within graph.ainvoke inherit this value automatically.
    set_fencing_token(fencing_token)

    # Bind the thread_id so all WARNING+ logs emitted during this run are
    # captured into the per-thread error-log store used for agent recovery.
    from backend.langgraph.agent.error_log import bind_log_thread_id

    bind_log_thread_id(thread_id)

    lock_lost_event = asyncio.Event()
    stop_renew = asyncio.Event()
    renew_task = asyncio.create_task(
        _renew_lock_loop(thread_id, stop_renew, lock_lost_event),
        name=f"lock-renew-{thread_id}",
    )

    register_thread(thread_id)
    try:
        graph = get_compiled_graph()

        if resume:
            config = {"configurable": {"thread_id": thread_id}}
            # Retrieve last checkpoint state and recover nodes
            checkpoint_state = await graph.aget_state(config)
            if checkpoint_state.values and isinstance(checkpoint_state.values, dict):
                current_nodes = checkpoint_state.values.get("nodes", {})
                if current_nodes:
                    recovered_nodes = await recover_graph_state_from_db(thread_id, current_nodes)
                    await graph.aupdate_state(config, {"nodes": recovered_nodes})
            final_state = await graph.ainvoke(None, config=config)

        elif query.startswith(_FORK_PREFIX):
            fork_config = json.loads(query[len(_FORK_PREFIX):])
            config = fork_config
            # Retrieve last checkpoint state for fork and recover nodes
            checkpoint_state = await graph.aget_state(config)
            if checkpoint_state.values and isinstance(checkpoint_state.values, dict):
                current_nodes = checkpoint_state.values.get("nodes", {})
                if current_nodes:
                    recovered_nodes = await recover_graph_state_from_db(thread_id, current_nodes)
                    await graph.aupdate_state(config, {"nodes": recovered_nodes})
            final_state = await graph.ainvoke(None, config=fork_config)

        else:
            async with raw_conn() as conn:
                await conn.execute(
                    "UPDATE fin_agents.user_queries "
                    "SET status = 'running' "
                    "WHERE thread_id = %s AND status = 'received'",
                    (thread_id,),
                )
            config = {"configurable": {"thread_id": thread_id}}
            initial_state = {"thread_id": thread_id, "query": query}
            final_state = await graph.ainvoke(initial_state, config=config)

        answer = final_state.get("conclusion") if isinstance(final_state, dict) else None
        await complete_thread(thread_id, answer=answer)

    except asyncio.CancelledError:
        # Fix 2: distinguish lock-loss abort from other cancellations.
        if lock_lost_event.is_set():
            logger.error(
                "[main_thread.executor] [%s] thread_id=%s fencing_token=%d"
                " -- zombie run aborted; new owner will complete the thread",
                MAIN_THREAD_LOCK_LOST, thread_id, fencing_token,
            )
            # Do NOT mark the thread as failed.  Fall through to finally for
            # zombie task cleanup and normal lock/cancel-flag cleanup.
            return
        # Non-lock-loss cancellation (e.g. uvicorn shutdown) -- re-raise.
        raise

    except Exception as exc:  # noqa: BLE001
        from backend.langgraph.lifecycle.errors import TaskPausedError, ThreadCancelledError
        if isinstance(exc, (ThreadCancelledError, TaskPausedError)):
            logger.debug(
                "[main_thread.executor] graph stopped thread_id=%s reason=%s",
                thread_id, type(exc).__name__,
            )
            return
        logger.error(
            "[main_thread.executor] graph failed thread_id=%s: %s",
            thread_id, exc,
            exc_info=True,
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
        # Fix 3: clean up orphaned task rows created during this zombie run.
        if lock_lost_event.is_set() and fencing_token > 0:
            try:
                from backend.langgraph.lifecycle.threads.nodes.tasks import (
                    cleanup_zombie_tasks,
                )
                await cleanup_zombie_tasks(thread_id, fencing_token)
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.error(
                    "[main_thread.executor] cleanup_zombie_tasks failed "
                    "thread_id=%s fencing_token=%d: %s",
                    thread_id, fencing_token, cleanup_exc,
                )


import json  # noqa: E402 -- imported after type-only top section


async def dispatch_graph_run(
    thread_id: str,
    query: str,
    *,
    resume: bool = False,
) -> None:
    """Acquire thread ownership lock and dispatch graph execution as asyncio.Task.

    Implements the full routing / ownership check with CAS steal (Fix 1):

    1. No lock -> acquire (returns fencing token) -> dispatch.
    2. Lock owned by this instance, task running -> idempotent no-op.
    3. Lock owned by this instance, task not running -> re-dispatch with
       existing token.
    4. Lock owned by live foreign instance -> raise :exc:`ThreadRoutingError`.
    5. Lock owned by dead foreign instance -> CAS steal (returns new token)
       -> dispatch; if CAS fails (another instance stole it first), re-check
       the new owner and route accordingly.

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
        MAIN_THREAD_STEAL_RACE,
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
    fencing_token: int = 0

    if existing_owner is not None:
        is_mine = (
            existing_owner.get("port") == owner_info["port"]
            and existing_owner.get("pid") == owner_info["pid"]
        )
        if is_mine:
            if is_running(thread_id):
                # Already running on this instance -- idempotent.
                return
            # Lock is ours but task finished/crashed -- re-dispatch with
            # the token already in the lock (no new increment).
            fencing_token = existing_owner.get("token", 0)
        else:
            # Lock belongs to a different instance.
            alive = await check_owner_alive(existing_owner)
            if alive:
                logger.error(
                    "[main_thread.executor] %s thread_id=%s owner_port=%d",
                    MAIN_THREAD_LOCK_CONFLICT, thread_id, existing_owner.get("port"),
                )
                raise ThreadRoutingError(existing_owner["port"])
            # Owner is dead -- CAS steal the lock.
            logger.error(
                "[main_thread.executor] %s thread_id=%s dead_port=%d",
                MAIN_THREAD_LOCK_STOLEN, thread_id, existing_owner.get("port"),
            )
            token = await steal_lock(thread_id, existing_owner)
            if token is None:
                # CAS failed -- another instance beat us to the steal.
                logger.error(
                    "[main_thread.executor] %s thread_id=%s",
                    MAIN_THREAD_STEAL_RACE, thread_id,
                )
                new_owner = await get_lock_owner(thread_id)
                if new_owner is not None:
                    alive = await check_owner_alive(new_owner)
                    if alive:
                        raise ThreadRoutingError(new_owner["port"])
                    # New owner is also dead -- retry steal once.
                    token = await steal_lock(thread_id, new_owner)
                    if token is None:
                        raise ThreadRoutingError(0)
                else:
                    # Lock vanished entirely -- fall through to acquire below.
                    token_from_acquire = await acquire_lock(thread_id)
                    if token_from_acquire is None:
                        raise ThreadRoutingError(0)
                    fencing_token = token_from_acquire
                    token = None  # skip outer fencing_token = token assignment
            if token is not None:
                fencing_token = token
    else:
        # No lock -- try to acquire.
        token = await acquire_lock(thread_id)
        if token is None:
            # Race: another instance just acquired it.
            existing_owner = await get_lock_owner(thread_id)
            if existing_owner is not None:
                alive = await check_owner_alive(existing_owner)
                if alive:
                    raise ThreadRoutingError(existing_owner["port"])
                # Dead already -- CAS steal.
                token = await steal_lock(thread_id, existing_owner)
                if token is None:
                    raise ThreadRoutingError(0)
            # Lock vanished between NX-fail and GET (extremely rare) -- proceed.
            fencing_token = token if token is not None else 0
        else:
            fencing_token = token

    task = asyncio.create_task(
        _run_graph(thread_id, query, resume=resume, fencing_token=fencing_token),
        name=f"graph-{thread_id}",
    )
    register(thread_id, task)


__all__ = ["ThreadRoutingError", "dispatch_graph_run"]
