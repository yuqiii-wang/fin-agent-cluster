"""backend.users.queries.retry — Business logic for retrying a completed/failed task.

Retry modes
-----------
``restart``
    Re-run the task from scratch with the same input.  Works for both
    streaming and non-streaming tasks.

``compact_and_continue``
    Streaming tasks only.  Reads the prior thinking tokens from
    ``fin_agents.llm_responses``, detects repeating lines, compresses the
    looping suffix, then dispatches a new streaming run that starts from
    the compressed context.  The final stored thinking is the concatenation
    of the prior and new thinking so the full reasoning chain is preserved.

Implementation notes
--------------------
Both retry modes run Celery workers (stream or completion) in an asyncio
background task so the HTTP response is returned immediately (HTTP 202).
The frontend tracks progress via the same Centrifugo SSE channel as any
other task execution.

Cancel flag
-----------
If the task was previously cancelled, the thread-level Redis cancel flag
may still be set.  ``retry_task`` clears it before dispatch to prevent the
new Celery run from being cancelled immediately on the first poll cycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import HTTPException

from backend.langgraph.lifecycle.threads.nodes.tasks import (
    complete_task,
    get_latest_llm_response,
    get_task_full,
    persist_task_result,
    reset_task_for_retry,
)
from backend.users.schemas import TaskInfo

logger = logging.getLogger(__name__)

# Terminal states that allow retry.
_RETRYABLE_STATUSES = {"completed", "failed", "cancelled", "paused"}


async def retry_task(thread_id: str, task_id: str, mode: str) -> TaskInfo:
    """Dispatch a retry of *task_id* and return immediately.

    Validates the task state, resets the DB row to ``running``, emits the
    ``task_status: running`` SSE, then spawns an asyncio background task
    that drives the Celery execution and emits the terminal SSE when done.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task UUID to retry.
        mode:      ``"restart"`` or ``"compact_and_continue"``.

    Returns:
        Updated :class:`~backend.users.schemas.TaskInfo` with status ``running``.

    Raises:
        HTTPException 404: Task or thread not found.
        HTTPException 409: Task is not in a retryable terminal state.
        HTTPException 422: ``compact_and_continue`` requested but no prior
                           LLM response exists.
    """
    from backend.api.threads.node.tasks.errors import (  # noqa: PLC0415
        TASK_RETRY_NOT_FOUND,
        TASK_RETRY_NOT_RETRYABLE,
        TASK_RETRY_NO_PRIOR_LLM_RESPONSE,
    )

    # 1. Fetch current task row (includes input and view metadata).
    task_row = await get_task_full(thread_id, task_id)
    if task_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"[{TASK_RETRY_NOT_FOUND}] task_id={task_id} thread_id={thread_id} not found",
        )

    if task_row["status"] not in _RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"[{TASK_RETRY_NOT_RETRYABLE}] task_id={task_id} "
                f"status={task_row['status']} is not retryable"
            ),
        )

    view_type: str = task_row["view_type"] or "ToolCall"
    is_streaming: bool = view_type == "Streaming"
    task_name: str = task_row["task_name"]
    node_id: str = task_row["node_id"] or ""
    node_name: str = task_row["node_name"] or ""
    input_data: dict[str, Any] = task_row.get("input") or {}
    stats_views: list[str] = list(task_row.get("stats_views") or [])

    # 2. For compact_and_continue: validate prior LLM response exists.
    prior_thinking_full: str = ""
    prior_thinking_compressed: str = ""
    if mode == "compact_and_continue":
        if not is_streaming:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"[{TASK_RETRY_NOT_RETRYABLE}] compact_and_continue "
                    "is only valid for streaming tasks"
                ),
            )
        llm_row = await get_latest_llm_response(task_id)
        if task_row["status"] == "paused":
            # Paused task: Redis snapshot holds the latest partial thinking
            # (written by _await_result when the stream worker exited gracefully).
            # Fall back to DB LLM response only if snapshot is absent (e.g. the
            # task was paused after a completed retry that left an LLM row).
            from backend.langgraph.lifecycle.pause_flag import get_task_pause_snapshot
            prior_thinking_full = await get_task_pause_snapshot(task_id)
        if not prior_thinking_full and llm_row and llm_row.get("thinking"):
            prior_thinking_full = llm_row["thinking"] or ""
        if not prior_thinking_full:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"[{TASK_RETRY_NO_PRIOR_LLM_RESPONSE}] "
                    f"no prior thinking found for task_id={task_id}"
                ),
            )
        non_rep, rep_block, rep_count = _compress_thinking(prior_thinking_full)
        if rep_count >= 2:
            prior_thinking_compressed = (
                non_rep
                + f"\n<repeating contents> x {rep_count}\n"
                + rep_block
            )
        else:
            prior_thinking_compressed = prior_thinking_full

    # 3. Clear the thread-level cancel flag and task-level pause flag.
    from backend.langgraph.lifecycle.cancel_flag import clear_cancel_flag
    from backend.langgraph.lifecycle.pause_flag import clear_task_pause_flag
    await clear_cancel_flag(thread_id)
    await clear_task_pause_flag(task_id)

    # 4. Reset task status to 'running' in DB and emit running SSE.
    reset_row = await reset_task_for_retry(thread_id, task_id)
    if reset_row is None:
        # Another concurrent retry beat us to it.
        raise HTTPException(
            status_code=409,
            detail=(
                f"[{TASK_RETRY_NOT_RETRYABLE}] task_id={task_id} "
                "could not be reset — may already be running"
            ),
        )

    # 4a. If the task was paused, also reset the node from paused → running.
    if task_row["status"] == "paused" and node_id:
        from backend.langgraph.lifecycle.threads.nodes.ops import resume_node  # noqa: PLC0415
        await resume_node(thread_id, node_id, node_name)

    # 5. Dispatch background asyncio task to drive Celery execution.
    #    Register the thread cancel token so cancel_all_running_threads() finds
    #    this retry, and register the asyncio.Task so wait_all() drains it on
    #    graceful shutdown.
    from backend.langgraph.lifecycle.threads.ops import register_thread as _register_thread
    from backend.main_thread import registry as _task_registry
    _register_thread(thread_id)
    bg_task = asyncio.create_task(
        _run_retry_background(
            thread_id=thread_id,
            task_id=task_id,
            task_name=task_name,
            node_id=node_id,
            node_name=node_name,
            input_data=input_data,
            is_streaming=is_streaming,
            mode=mode,
            view_type=view_type,
            prior_thinking_full=prior_thinking_full,
            prior_thinking_compressed=prior_thinking_compressed,
        ),
        name=f"retry:{task_id}",
    )
    _task_registry.register(thread_id, bg_task)

    return TaskInfo(
        task_id=task_id,
        thread_id=thread_id,
        node_id=node_id,
        node_name=node_name,
        task_name=task_name,
        status="running",
        view_type=view_type,
        stats_views=stats_views,
        is_streaming=is_streaming,
        input=input_data,
    )


async def _run_retry_background(
    *,
    thread_id: str,
    task_id: str,
    task_name: str,
    node_id: str,
    node_name: str,
    input_data: dict[str, Any],
    is_streaming: bool,
    mode: str,
    view_type: str,
    prior_thinking_full: str,
    prior_thinking_compressed: str,
) -> None:
    """Background coroutine: dispatch Celery task, await result, emit terminal SSE.

    Runs entirely in the FastAPI asyncio event loop.  Errors are logged and
    the task is marked failed so the UI is not left in a permanent running state.

    Args:
        thread_id:               LangGraph thread UUID.
        task_id:                 Task UUID.
        task_name:               Handler key / UI label.
        node_id:                 Owning node ID.
        node_name:               Owning node name.
        input_data:              Serialised task input payload.
        is_streaming:            Whether this is a streaming task.
        mode:                    Retry mode (``"restart"`` or ``"compact_and_continue"``).
        view_type:               Task view type string.
        prior_thinking_full:     Full prior thinking for compact_and_continue.
        prior_thinking_compressed: Compressed prior thinking for compact_and_continue.
    """
    from backend.celery_task.celery_engine import celery_engine
    from backend.celery_task.config import get_ondemand_queue, get_stream_queue
    from backend.celery_task.workers.task_delegation import _await_result, _COMPLETION_TIMEOUT, _STREAM_TIMEOUT  # noqa: PLC2701
    from backend.api.threads.node.tasks.errors import TASK_RETRY_DISPATCH_FAILED  # noqa: PLC0415

    try:
        if is_streaming and mode == "compact_and_continue":
            async_result = celery_engine.send_task(
                "backend.celery_task.workers.tasks.stream_task.run_stream_compact_continue",
                args=[
                    thread_id, task_id, task_name, node_name, input_data,
                    prior_thinking_full, prior_thinking_compressed,
                ],
                queue=get_stream_queue(thread_id),
            )
            result = await _await_result(async_result, thread_id, task_id, _STREAM_TIMEOUT)
        elif is_streaming:
            async_result = celery_engine.send_task(
                "backend.celery_task.workers.tasks.stream_task.run_stream",
                args=[thread_id, task_id, task_name, node_name, input_data],
                queue=get_stream_queue(thread_id),
            )
            result = await _await_result(async_result, thread_id, task_id, _STREAM_TIMEOUT)
        else:
            async_result = celery_engine.send_task(
                "backend.celery_task.workers.tasks.completion_task.run_completion",
                args=[thread_id, task_id, node_id, node_name, task_name, input_data],
                queue=get_ondemand_queue(thread_id),
            )
            result = await _await_result(
                async_result, thread_id, task_id, _COMPLETION_TIMEOUT, node_id=node_id,
            )
    except Exception as exc:
        from backend.langgraph.lifecycle.errors import TaskPausedError
        if isinstance(exc, TaskPausedError):
            # Task was paused again during retry — lifecycle already handled by
            # pause_task_by_uuid; nothing more to do here.
            return
        logger.error(
            "[%s] retry background failed task_id=%s task_name=%s thread_id=%s: %s",
            TASK_RETRY_DISPATCH_FAILED, task_id, task_name, thread_id, exc,
        )
        await complete_task(
            thread_id, node_id, node_name, task_id, task_name,
            failed=True,
            error=str(exc),
            view_type=view_type,
        )
        return

    await complete_task(
        thread_id, node_id, node_name, task_id, task_name,
        output_data=result,
        view_type=view_type,
    )
    await _maybe_dispatch_graph_resume(thread_id, node_id)


async def _maybe_dispatch_graph_resume(thread_id: str, node_id: str) -> None:
    """Re-invoke graph from checkpoint when all sibling tasks for *node_id* complete.

    After a resumed task finishes successfully, checks whether all tasks for the
    owning node are in a terminal state.  If so, dispatches a graph resume so
    the graph calls ``complete_node`` and ``complete_thread`` naturally.  Safe
    to call concurrently from parallel resumed tasks: ``dispatch_graph_run`` is
    idempotent when a run is already active (routing case 2).

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Owning node UUID.
    """
    from backend.db.postgres import raw_conn
    from backend.main_thread.executor import dispatch_graph_run

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM fin_agents.tasks "
            "WHERE node_id = %s "
            "AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')",
            (node_id,),
        )
        row = await cur.fetchone()
    if (row["cnt"] if row else 1) > 0:
        return
    await dispatch_graph_run(thread_id, "", resume=True)


def _compress_thinking(thinking: str) -> tuple[str, str, int]:
    """Delegate to the stream_task repetition detector.

    Imported lazily to avoid circular imports at module load time.

    Args:
        thinking: Raw prior thinking text.

    Returns:
        ``(non_repeating, repeating_block, repeat_count)``
    """
    from backend.celery_task.workers.tasks.stream_task import _detect_and_compress_repetition
    return _detect_and_compress_repetition(thinking)


async def _bg_await_and_restart(
    thread_id: str,
    task_id: str,
    celery_result: Any | None,
) -> None:
    """Wait for the old Celery worker to finish, then restart the task.

    Polls the thread registry until the Celery result for *task_id* has been
    discarded (meaning the old worker has fully exited and its result was
    processed by ``_await_result``).  Only then calls :func:`retry_task` so
    there is no window where two workers for the same task run simultaneously.

    Args:
        thread_id:     LangGraph thread UUID.
        task_id:       Task governance UUID.
        celery_result: The Celery ``AsyncResult`` captured before pausing, or
                       ``None`` if there was no active worker (already paused /
                       just completed naturally).
    """
    from backend.langgraph.lifecycle.threads.manager import get_thread_registry
    from backend.api.threads.node.tasks.errors import TASK_RETRY_DISPATCH_FAILED  # noqa: PLC0415

    registry = get_thread_registry()
    if celery_result is not None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 60  # 60 s safety timeout
        while loop.time() < deadline:
            if registry.get_celery_result(task_id) is None:
                break
            await asyncio.sleep(0.1)
    try:
        await retry_task(thread_id, task_id, mode="restart")
    except Exception as exc:
        logger.error(
            "[%s] retry_fresh bg restart failed task_id=%s thread_id=%s: %s",
            TASK_RETRY_DISPATCH_FAILED, task_id, thread_id, exc,
        )


async def retry_fresh_task(thread_id: str, task_id: str) -> TaskInfo:
    """Pause a running task if needed, then restart it from scratch.

    If the task is currently ``running``, pauses it atomically (setting the
    Redis pause flag and marking the DB row as ``paused``) and schedules an
    asyncio background task that waits for the old Celery worker to exit
    before restarting.  Returns immediately with the ``paused`` task info.

    If the task is already in a retryable terminal state
    (``paused`` / ``failed`` / ``cancelled`` / ``completed``), restarts it
    synchronously and returns the ``running`` task info.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task governance UUID.

    Returns:
        Updated :class:`~backend.users.schemas.TaskInfo` — either ``paused``
        (restart pending) or ``running`` (restart already dispatched).

    Raises:
        HTTPException 404: Task or thread not found.
        HTTPException 409: Task is in a non-retryable state (e.g. ``wrong``).
    """
    from backend.api.threads.node.tasks.errors import (  # noqa: PLC0415
        TASK_RETRY_NOT_FOUND,
        TASK_RETRY_NOT_RETRYABLE,
    )
    from backend.langgraph.lifecycle.threads.manager import get_thread_registry
    from backend.users.queries.lifecycle import pause_task_by_uuid  # noqa: PLC0415

    task_row = await get_task_full(thread_id, task_id)
    if task_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"[{TASK_RETRY_NOT_FOUND}] task_id={task_id} thread_id={thread_id} not found",
        )

    status: str = task_row["status"]

    if status == "running":
        # Step 1: pause immediately — marks DB as 'paused' and emits SSE so
        # the frontend learns the new status.  The Redis pause flag signals
        # the Celery worker to stop gracefully.
        await pause_task_by_uuid(thread_id, task_id)

        # Step 2: capture the Celery result AFTER pausing so we know which
        # result handle to watch.  The handle may already be None if the
        # worker happened to finish naturally between our DB read and the
        # pause call — in that case the background task skips the wait.
        registry = get_thread_registry()
        celery_result = registry.get_celery_result(task_id)

        # Step 3: schedule restart once the old worker has fully exited.
        asyncio.create_task(
            _bg_await_and_restart(thread_id, task_id, celery_result),
        )

        view_type: str = task_row.get("view_type") or "ToolCall"
        return TaskInfo(
            task_id=task_id,
            thread_id=thread_id,
            node_id=task_row.get("node_id") or "",
            node_name=task_row.get("node_name") or "",
            task_name=task_row.get("task_name") or "",
            status="paused",
            view_type=view_type,
            is_streaming=view_type == "Streaming",
        )

    if status in _RETRYABLE_STATUSES:
        return await retry_task(thread_id, task_id, mode="restart")

    raise HTTPException(
        status_code=409,
        detail=(
            f"[{TASK_RETRY_NOT_RETRYABLE}] task_id={task_id} "
            f"status={status} is not retryable"
        ),
    )


async def continue_task(thread_id: str, task_id: str) -> TaskInfo:
    """Continue a paused streaming task from where it left off.

    Equivalent to :func:`retry_task` with ``mode="compact_and_continue"``.
    Only valid for tasks currently in the ``paused`` state.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task governance UUID.

    Returns:
        Updated :class:`~backend.users.schemas.TaskInfo` with status ``running``.

    Raises:
        HTTPException 404: Task or thread not found.
        HTTPException 409: Task is not in the ``paused`` state.
    """
    from backend.api.threads.node.tasks.errors import (  # noqa: PLC0415
        TASK_RETRY_NOT_FOUND,
        TASK_CONTINUE_NOT_PAUSED,
    )

    task_row = await get_task_full(thread_id, task_id)
    if task_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"[{TASK_RETRY_NOT_FOUND}] task_id={task_id} thread_id={thread_id} not found",
        )

    if task_row["status"] != "paused":
        raise HTTPException(
            status_code=409,
            detail=(
                f"[{TASK_CONTINUE_NOT_PAUSED}] task_id={task_id} "
                f"status={task_row['status']} is not paused; cannot continue"
            ),
        )

    return await retry_task(thread_id, task_id, mode="compact_and_continue")


async def retry_restart_task(thread_id: str, task_id: str) -> TaskInfo:
    """Restart a terminal task from scratch, dropping all existing output.

    A lightweight alternative to :func:`retry_fresh_task` that performs no
    pause coordination — the task must already be in a retryable terminal
    state (``completed`` / ``failed`` / ``cancelled`` / ``paused``).

    Intended for non-streaming completion tasks where there is no Celery
    stream worker to wait for.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task governance UUID.

    Returns:
        Updated :class:`~backend.users.schemas.TaskInfo` with status ``running``.

    Raises:
        HTTPException 404: Task or thread not found.
        HTTPException 409: Task is not in a retryable terminal state.
    """
    from backend.api.threads.node.tasks.errors import (  # noqa: PLC0415
        TASK_RETRY_NOT_FOUND,
        TASK_RETRY_NOT_RETRYABLE,
    )

    task_row = await get_task_full(thread_id, task_id)
    if task_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"[{TASK_RETRY_NOT_FOUND}] task_id={task_id} thread_id={thread_id} not found",
        )

    if task_row["status"] not in _RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"[{TASK_RETRY_NOT_RETRYABLE}] task_id={task_id} "
                f"status={task_row['status']} is not a retryable terminal state"
            ),
        )

    return await retry_task(thread_id, task_id, mode="restart")


__all__ = ["retry_task", "retry_fresh_task", "retry_restart_task", "continue_task"]

