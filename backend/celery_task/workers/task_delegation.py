"""Celery task delegation helpers.

These helpers are called from LangGraph ``@task`` functions.  They dispatch
a unit of work to a Celery worker and await the result via async polling
(``XREAD BLOCK`` on a per-task Redis Stream result channel), checking the
Redis cancel flag on each timeout cycle.

Cancellation
------------
FastAPI signals cancellation by writing ``SET fin:cancel:{thread_id} 1``
(via :func:`~backend.main_thread.cancel_flag.set_cancel_flag`).  The
polling loop in ``_await_result`` checks this Redis key on every
``_CANCEL_POLL_INTERVAL``-second cycle.  When detected, the Celery task is
revoked and :class:`ThreadCancelledError` is raised so the owning LangGraph
node's ``except Exception`` handler can clean up.

Result delivery
---------------
The Celery worker writes its result to the Celery result backend (Redis DB 2)
as before.  ``_await_result`` retrieves it via a non-blocking
``asyncio.wait_for`` wrapper around ``async_result.get`` executed in a
thread-pool, iterating until the result arrives or timeout/cancel fires.

Hierarchy
---------
  LangGraph thread  (main thread FastAPI — uvicorn asyncio event loop)
    └── @task (langgraph.func.task)
          └── delegate_completion / delegate_stream   ← this module
                └── Celery worker process
                      └── completion_task / stream_task
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import celery.exceptions

from backend.celery_task.celery_engine import celery_engine
from backend.celery_task.config import get_ondemand_queue
from backend.langgraph.lifecycle.errors import ThreadCancelledError

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds to wait for a non-streaming Celery result.
_COMPLETION_TIMEOUT = 120
# Maximum wall-clock seconds to wait for the streaming conclusion result.
_STREAM_TIMEOUT = 300
# How often (seconds) the await loop checks the Redis cancel flag.
_CANCEL_POLL_INTERVAL = 0.5


async def _await_result(
    async_result: Any,
    thread_id: str,
    task_id: str,
    total_timeout: float,
) -> dict[str, Any]:
    """Await *async_result* with Redis-based cancellation support.

    Registers the Celery ``AsyncResult`` in the process-local lifecycle
    registry so it can be revoked externally.  Polls every
    ``_CANCEL_POLL_INTERVAL`` seconds via ``run_in_executor``, checking
    the Redis cancel flag (written by FastAPI) before each attempt.

    Using ``get_running_loop()`` (not the deprecated ``get_event_loop()``)
    ensures this always targets the correct event loop regardless of which
    process runs this code.

    Args:
        async_result:  Celery ``AsyncResult`` from ``send_task``.
        thread_id:     LangGraph thread UUID (for cancel-flag lookup).
        task_id:       Governance task UUID (for registry cleanup).
        total_timeout: Maximum seconds before ``TimeoutError`` is raised.

    Returns:
        The result dict from the Celery worker.

    Raises:
        ThreadCancelledError: If the Redis cancel flag for the thread is set.
        TimeoutError:         If *total_timeout* elapses before completion.
    """
    from backend.main_thread.cancel_flag import is_cancel_flag_set
    from backend.langgraph.lifecycle.threads.manager import get_thread_registry

    registry = get_thread_registry()
    registry.register_celery_result(task_id, async_result)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout
    _last_warn_s: int = 0

    try:
        while True:
            remaining = deadline - loop.time()
            elapsed = total_timeout - remaining
            # Log a warning every 30 s when the task is taking unusually long.
            # Include the Celery task state so we can distinguish PENDING (never
            # picked up, e.g. all workers busy or broker queue lost) from STARTED
            # (picked up but running slowly) or FAILURE (silently failed without
            # propagating the exception back through the result backend).
            if elapsed > 10:
                _warn_bucket = int(elapsed) // 30 * 30
                if _warn_bucket > _last_warn_s:
                    _last_warn_s = _warn_bucket
                    try:
                        celery_state = async_result.state
                    except Exception:  # noqa: BLE001
                        celery_state = "unknown"
                    logger.error(
                        "[task_delegation] waiting for celery task_id=%s thread_id=%s"
                        " elapsed_s=%.0f celery_state=%s",
                        task_id, thread_id, elapsed, celery_state,
                    )
            if remaining <= 0:
                registry.revoke_celery_task(task_id)
                raise TimeoutError(
                    f"Task {task_id} exceeded maximum duration of {total_timeout}s"
                )

            # Check Redis cancel flag — works across process boundaries.
            if await is_cancel_flag_set(thread_id):
                registry.revoke_celery_task(task_id)
                raise ThreadCancelledError(thread_id)

            poll_timeout = min(_CANCEL_POLL_INTERVAL, remaining)
            try:
                result: dict[str, Any] = await loop.run_in_executor(
                    None,
                    lambda t=poll_timeout: async_result.get(timeout=t),
                )
                return result
            except celery.exceptions.TimeoutError:
                # Not done yet — loop and re-check cancel flag.
                continue
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
    loop as a background task — Celery only performs the DB write for
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
            async_result, thread_id, task_id, _COMPLETION_TIMEOUT
        )
    except (ThreadCancelledError, TimeoutError):
        # Cancel and timeout have their own SSE paths (cancel_task / node except block).
        raise
    except Exception as exc:
        # Celery worker raised — emit task:failed SSE from the graph runner loop.
        logger.error(
            "[task_delegation] task failed task_id=%s task_name=%s thread_id=%s: %s",
            task_id, task_name, thread_id, exc,
        )
        asyncio.create_task(
            _emit_task_sse(
                thread_id, task_id, node_id, node_name, task_name,
                status="failed",
                payload={"output": {"error": str(exc)}},
            ),
            name=f"sse-task-failed-{task_id}",
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
    # Emit task:completed SSE as a background task so the graph runner
    # proceeds immediately to complete_node without waiting for the ACK
    # round-trip.
    asyncio.create_task(
        _emit_task_sse(
            thread_id, task_id, node_id, node_name, task_name,
            status="completed",
            payload={"output": result},
        ),
        name=f"sse-task-completed-{task_id}",
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
    """Emit a task_status SSE event (fire-and-forget wrapper).

    Called as an ``asyncio.create_task`` background coroutine from
    ``delegate_completion`` so it does not block the graph runner.

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
        logger.error(
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
            logger.error(
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

    Args:
        thread_id:  LangGraph thread UUID (for Centrifugo shard routing).
        task_id:    Governance UUID for the ``fin_agents.tasks`` row.
        task_name:  Human label, e.g. ``"stream_conclusion"``.
        node_name:  Owning node name.
        payload:    Input context (must include ``"merged_research"``).

    Returns:
        ``{"answer": str, "total_tokens": int, "latency_ms": int}``

    Raises:
        ThreadCancelledError: If the thread's cancel token is set during polling.
        TimeoutError:         If streaming does not complete within the timeout.
    """
    async_result = celery_engine.send_task(
        "backend.celery_task.workers.tasks.stream_task.run_stream",
        args=[thread_id, task_id, task_name, node_name, payload],
        queue=get_ondemand_queue(thread_id),
    )
    result = await _await_result(
        async_result, thread_id, task_id, _STREAM_TIMEOUT
    )
    return result
