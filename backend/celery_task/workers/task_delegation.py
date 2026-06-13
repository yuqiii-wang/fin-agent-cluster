"""Celery task delegation helpers.

These helpers are called from LangGraph ``@task`` functions.  They dispatch
a unit of work to a Celery worker and await the result via async polling
(``XREAD BLOCK`` on a per-task Redis Stream result channel), checking the
Redis cancel flag on each timeout cycle.

Cancellation
------------
FastAPI signals cancellation by writing ``SET fin:cancel:{thread_id} 1``
(via :func:`~backend.langgraph.lifecycle.cancel_flag.set_cancel_flag`).  The
polling loop in ``_await_result`` checks this Redis key on every
``_CANCEL_POLL_INTERVAL``-second cycle.  When detected, the Celery task is
revoked and :class:`ThreadCancelledError` is raised so the owning LangGraph
node's ``except Exception`` handler can clean up.

Result delivery
---------------
The Celery worker writes its result to the Celery result backend (Redis DB 2).
``_await_result`` polls ``celery-task-meta-{task_id}`` directly via a shared
``redis.asyncio`` client, avoiding the synchronous Celery backend connection
pool that caused Protocol Errors under parallel node execution.

Hierarchy
---------
  LangGraph thread  (main thread FastAPI -- uvicorn asyncio event loop)
    └── @task (langgraph.func.task)
          └── delegate_completion / delegate_stream   <- this module
                └── Celery worker process
                      └── completion_task / stream_task
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any

from backend.celery_task.celery_engine import celery_engine
from backend.celery_task.config import get_ondemand_queue, get_stream_queue
from backend.langgraph.lifecycle.errors import TaskPausedError, ThreadCancelledError

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds to wait for a non-streaming Celery result.
_COMPLETION_TIMEOUT = 120
# Maximum wall-clock seconds to wait for the streaming conclusion result.
_STREAM_TIMEOUT = 1800
# How often (seconds) the await loop checks the Redis cancel flag.
_CANCEL_POLL_INTERVAL = 0.5



async def _await_result(
    async_result: Any,
    thread_id: str,
    task_id: str,
    total_timeout: float,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Await *async_result* by polling the Celery result backend via async Redis.

    Polls ``celery-task-meta-{celery_task_id}`` directly using the shared
    ``redis.asyncio`` client (DB 2, shard 0) instead of calling
    ``async_result.get()`` in a thread-pool executor.  This prevents the
    Protocol Errors that occur when two concurrent ``run_in_executor`` threads
    (e.g. stats_node + news_node) share the synchronous Celery backend
    connection pool and corrupt each other's TCP reads.

    Args:
        async_result:  Celery ``AsyncResult`` from ``send_task``.
        thread_id:     LangGraph thread UUID (for cancel-flag lookup).
        task_id:       Governance task UUID (for registry cleanup).
        total_timeout: Maximum seconds before ``TimeoutError`` is raised.
        node_id:       Owning node UUID.  When provided the loop also checks
                       the per-node cancel flag so a single-node cancel exits
                       quickly instead of waiting for the full task timeout.

    Returns:
        The result dict from the Celery worker.

    Raises:
        NodeCancelledError:  If the per-node cancel flag for *node_id* is set.
        ThreadCancelledError: If the Redis cancel flag for the thread is set.
        TimeoutError:         If *total_timeout* elapses before completion.
    """
    from backend.celery_task.config import CELERY_BACKEND_DB
    from backend.db.redis.client import get_client
    from backend.langgraph.lifecycle.cancel_flag import is_cancel_flag_set, is_node_cancel_flag_set
    from backend.langgraph.lifecycle.threads.manager import get_thread_registry
    from backend.langgraph.lifecycle.errors import NodeCancelledError

    registry = get_thread_registry()
    registry.register_celery_result(task_id, async_result)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout
    _last_warn_s: int = 0
    result_key = f"celery-task-meta-{async_result.id}"
    client = await get_client(shard=0, db=CELERY_BACKEND_DB)

    try:
        while True:
            remaining = deadline - loop.time()
            elapsed = total_timeout - remaining
            # Log a warning every 30 s when the task is taking unusually long.
            if elapsed > 10:
                _warn_bucket = int(elapsed) // 30 * 30
                if _warn_bucket > _last_warn_s:
                    _last_warn_s = _warn_bucket
                    logger.warning(
                        "[task_delegation] waiting for celery task_id=%s thread_id=%s"
                        " elapsed_s=%.0f",
                        task_id, thread_id, elapsed,
                    )
            if remaining <= 0:
                registry.revoke_celery_task(task_id)
                raise TimeoutError(
                    f"Task {task_id} exceeded maximum duration of {total_timeout}s"
                )

            # Check Redis cancel flag -- works across process boundaries.
            if await is_cancel_flag_set(thread_id):
                registry.revoke_celery_task(task_id)
                raise ThreadCancelledError(thread_id)

            # Check per-node cancel flag -- set by cancel_node API for single-node
            # cancellation (e.g. one branch of a parallel group cancelled by user).
            if node_id and await is_node_cancel_flag_set(node_id):
                registry.revoke_celery_task(task_id)
                raise NodeCancelledError(node_id)

            raw = await client.get(result_key)
            if raw is not None:
                data = _json.loads(raw)
                status = data.get("status")
                if status == "SUCCESS":
                    result = data["result"]
                    if isinstance(result, dict) and result.get("paused"):
                        thinking = result.get("thinking") or ""
                        if thinking:
                            from backend.langgraph.lifecycle.pause_flag import save_task_pause_snapshot
                            await save_task_pause_snapshot(task_id, thinking)
                        raise TaskPausedError(task_id, thinking)
                    return result
                if status == "FAILURE":
                    tb = data.get("traceback") or str(data.get("result", "unknown error"))
                    raise Exception(f"Celery task failed: {tb}")
                if status == "REVOKED":
                    # Task was revoked. Check whether this was a pause (task-level
                    # pause flag set) or a full thread/node cancellation.
                    from backend.langgraph.lifecycle.pause_flag import is_task_pause_flag_set
                    if await is_task_pause_flag_set(task_id):
                        raise TaskPausedError(task_id)
                    raise ThreadCancelledError(thread_id)
                # PENDING / STARTED / RETRY -- keep polling

            await asyncio.sleep(min(_CANCEL_POLL_INTERVAL, remaining))
    finally:
        registry.discard_celery_result(task_id)


async def delegate_completion(
    thread_id: str,
    task_id: str,
    node_id: str,
    node_name: str,
    task_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a non-streaming task to a Celery completion worker.

    Runs in the LangGraph asyncio event loop; polls in a thread-pool executor
    with cancel-token checking until the result is available.  Emits the
    ``task_status: completed`` (or ``failed``) SSE event from this asyncio
    loop as a background task -- Celery only performs the DB write for
    durability.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID of the owning ``fin_agents.tasks`` row.
        node_id:    Owning node's ID.
        node_name:  Owning node's human-readable name.
        task_name:  Key understood by ``completion_task.run_completion``
                    (e.g. ``"analyze_query"``, ``"read_stats"``).
        payload:    Arbitrary input forwarded to the handler.

    Returns:
        Handler result dict from the worker.

    Raises:
        ThreadCancelledError: If the thread's cancel token is set during polling.
        TimeoutError:         If the worker does not respond within the timeout.
    """
    import time as _time
    async_result = celery_engine.send_task(
        "backend.celery_task.workers.tasks.completion_task.run_completion",
        args=[thread_id, task_id, node_id, node_name, task_name, payload],
        queue=get_ondemand_queue(thread_id),
    )
    _t_dispatch = _time.monotonic()
    try:
        result = await _await_result(
            async_result, thread_id, task_id, _COMPLETION_TIMEOUT, node_id=node_id
        )
    except TaskPausedError:
        raise
    except (ThreadCancelledError, TimeoutError):
        # Cancel and timeout have their own SSE paths (cancel_task / node except block).
        raise
    except Exception as exc:
        # Celery worker raised -- emit task:failed SSE before re-raising so the
        # failure event arrives at the UI before any node-level events.
        logger.error(
            "[task_delegation] task failed task_id=%s task_name=%s thread_id=%s: %s",
            task_id, task_name, thread_id, exc,
        )
        await _emit_task_sse(
            thread_id, task_id, node_id, node_name, task_name,
            status="failed",
            payload={"output": {"error": str(exc)}},
        )
        raise

    _celery_ms = (_time.monotonic() - _t_dispatch) * 1000
    if _celery_ms > 5000:
        logger.error(
            "[task_delegation] slow celery task_id=%s task_name=%s thread_id=%s celery_ms=%.0f",
            task_id, task_name, thread_id, _celery_ms,
        )
    else:
        logger.debug(
            "[task_delegation] celery done task_id=%s task_name=%s celery_ms=%.0f",
            task_id, task_name, _celery_ms,
        )
    # Await task:completed SSE so the event is published and ACKed before
    # delegate_completion returns.  This guarantees task:completed arrives at
    # the UI before complete_node fires node:completed, preventing out-of-order
    # events on the shared Centrifugo thread channel.
    await _emit_task_sse(
        thread_id, task_id, node_id, node_name, task_name,
        status="completed",
        payload={"output": result},
    )
    return result


async def _emit_task_sse(
    thread_id: str,
    task_id: str,
    node_id: str,
    node_name: str,
    task_name: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    """Emit a task_status SSE event and await ACK before returning.

    Called from ``delegate_completion`` (awaited, not as a background task)
    so that task:completed / task:failed is published and ACKed before
    ``complete_node`` fires its own node-level SSE.  This enforces
    task -> node -> subgraph -> next_node ordering on the shared Centrifugo
    thread channel.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task UUID.
        node_id:   Owning node ID.
        node_name: Owning node name.
        task_name: Handler key (for SSE payload).
        status:    ``"completed"`` or ``"failed"``.
        payload:   Additional SSE payload fields.
    """
    try:
        from backend.centrifugo_mq.sse_notification.thread.node.task import notify
        logger.debug(
            "[task_delegation] emitting task SSE task_id=%s task_name=%s status=%s thread_id=%s",
            task_id, task_name, status, thread_id,
        )
        acked = await notify(
            thread_id=thread_id,
            task_id=task_id,
            event="task_status",
            payload={
                "status": status,
                "task_name": task_name,
                "node_id": node_id,
                "node_name": node_name,
                **payload,
            },
            dedup_key=f"task:{task_id}:{status}",
        )
        if not acked:
            logger.error(
                "[task_delegation] task SSE not acked task_id=%s task_name=%s status=%s thread_id=%s",
                task_id, task_name, status, thread_id,
            )
        else:
            logger.debug(
                "[task_delegation] task SSE acked task_id=%s task_name=%s status=%s thread_id=%s",
                task_id, task_name, status, thread_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[task_delegation] task SSE publish error task_id=%s status=%s: %s",
            task_id, status, exc,
        )


async def delegate_stream(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a streaming LLM task to a Celery stream worker.

    Tokens are streamed from the worker to the frontend via Centrifugo while
    the LangGraph thread polls for the final result dict.

    If a pause snapshot exists for *task_id* in Redis (set when the task was
    paused mid-stream), dispatches ``run_stream_compact_continue`` so the LLM
    continues from the saved thinking context rather than starting over.

    Args:
        thread_id:  LangGraph thread UUID (for Centrifugo shard routing).
        task_id:    Governance UUID for the ``fin_agents.tasks`` row.
        task_name:  UI-facing label for this streaming task (e.g. ``"stream_llm"``).
                    Decided by each node's task -- independent of the underlying
                    Celery task registration name (always ``run_stream``).
        node_name:  Owning node name.
        payload:    Input context forwarded to the stream worker.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``

    Raises:
        ThreadCancelledError: If the thread's cancel token is set during polling.
        TimeoutError:         If streaming does not complete within the timeout.
    """
    from backend.langgraph.lifecycle.pause_flag import get_task_pause_snapshot
    snapshot = await get_task_pause_snapshot(task_id)
    if snapshot:
        from backend.celery_task.workers.tasks.stream_utils import (
            detect_and_compress_repetition as _compress,
        )
        non_rep, rep_block, rep_count = _compress(snapshot)
        compressed = (
            non_rep + f"\n<repeating contents> x {rep_count}\n" + rep_block
            if rep_count >= 2
            else snapshot
        )
        async_result = celery_engine.send_task(
            "backend.celery_task.workers.tasks.stream_task.run_stream_compact_continue",
            args=[thread_id, task_id, task_name, node_name, payload, snapshot, compressed],
            queue=get_stream_queue(thread_id),
        )
    else:
        async_result = _send_to_stream_worker(thread_id, task_id, task_name, node_name, payload)
    try:
        result = await _await_result(
            async_result, thread_id, task_id, _STREAM_TIMEOUT
        )
    except TaskPausedError:
        raise
    except (ThreadCancelledError, TimeoutError):
        raise
    except Exception as exc:
        logger.error(
            "[task_delegation] stream task failed task_id=%s task_name=%s thread_id=%s: %s",
            task_id, task_name, thread_id, exc,
        )
        raise
    return result


def _send_to_stream_worker(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
) -> Any:
    """Route *task_name* to the shared ``run_stream`` Celery task on the stream queue.

    Decouples the UI-facing task name (set by each node's task, stored in
    ``fin_agents.tasks``, surfaced to the frontend) from the Celery task
    registration name (``stream_task.run_stream``), which is always the same
    regardless of which node's streaming task is dispatching.  Any node that
    wants LLM streaming simply calls :func:`delegate_stream` with its own
    ``task_name``; this helper ensures all such calls share the same worker pool.

    Args:
        thread_id:  LangGraph thread UUID (for stream-queue shard routing).
        task_id:    Governance UUID for the ``fin_agents.tasks`` row.
        task_name:  UI-facing label forwarded to the worker (used for prompt
                    builder lookup and result persistence).
        node_name:  Owning node name forwarded to the worker.
        payload:    Input context forwarded to the worker.

    Returns:
        Celery ``AsyncResult`` -- pass to ``_await_result`` to retrieve the
        final streaming result dict.
    """
    return celery_engine.send_task(
        "backend.celery_task.workers.tasks.stream_task.run_stream",
        args=[thread_id, task_id, task_name, node_name, payload],
        queue=get_stream_queue(thread_id),
    )
