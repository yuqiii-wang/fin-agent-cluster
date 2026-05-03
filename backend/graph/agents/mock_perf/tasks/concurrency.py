"""concurrency -- run_concurrency_task wraps the full concurrency stream lifecycle.

Concurrency mode
----------------
Celery ingest rate-limits token writes at ``token_per_sec`` TPS and stops when
the frontend signals stability via ``POST /perf/stable`` or the ``timeout_secs``
deadline is reached.

Ingest and delivery are **simultaneous** -- tokens are consumed by Centrifugo as
they are written, so no separate backend ``digesting`` phase is emitted.  The
frontend auto-transitions ``ingesting -> digesting`` on the first ``token_batch``
event.
"""

from __future__ import annotations

import asyncio
import logging
import time

from backend.db.redis.session.query_phase import set_query_phase
from backend.graph.agents.mock_perf.errors import STREAM_PUBLISH_FAILED
from backend.graph.agents.mock_perf.tasks.models import MockTaskResult
from backend.graph.utils.execution_log import finish_node_execution
from backend.llm.stream_events import publish_completion
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
)
from backend.sse_notifications.task import fail_task
from backend.sse_notifications.thread import emit_query_status
from backend.sse_notifications.stream import (
    emit_ingest_complete,
    emit_stream_complete,
    emit_stream_stopped,
)

_NODE_NAME: str = "mock_runner"
logger = logging.getLogger(__name__)


async def run_concurrency_task(
    thread_id: str,
    token_per_sec: int,
    timeout_secs: int,
    node_execution_id: int,
    t0_node: float,
    node_id: str,
    task_id: str,
    stream_id: str,
    run_id: str,
) -> MockTaskResult:
    """Wrap the concurrency stream lifecycle: ingest + deliver simultaneously.

    Ingest is coordinated by the fanout scheduler: a single coordinator
    ``asyncio.Task`` manages all streams in the run and dispatches them to
    a single Celery fanout task so every stream gets to produce tokens even
    when the number of streams exceeds the worker count.

    Args:
        thread_id:          LangGraph thread UUID.
        token_per_sec:      Target publish rate (tokens/s).
        timeout_secs:       Hard deadline in seconds.
        node_execution_id:  DB row ID from :func:`start_node_execution`.
        t0_node:            ``time.monotonic()`` captured at node entry.
        node_id:            Node execution UUID.
        task_id:          Task invocation UUID (task-level identity).
        stream_id:          Streaming session UUID (Celery ingest run).
        run_id:             Shared run UUID for coordinator dispatch.

    Returns:
        :class:`MockTaskResult` with task ID, task_id, produced count, TPS, and summary.

    Raises:
        asyncio.CancelledError: When the task is cancelled (already cleaned up).
        Exception:              On ingest failure (already cleaned up).
    """
    from backend.graph.agents.mock_perf.tasks.coordinator import dispatch_scheduled_ingest  # noqa: PLC0415

    await set_query_phase(thread_id, "ingesting")
    await emit_query_status(thread_id, "ingesting", stream_id=stream_id)

    pub_task_id = await create_task(
        thread_id,
        "MOCK_RUNNER_CONCURRENCY",
        node_execution_id,
        provider="mock",
        extra_payload={
            "node_id": node_id,
            "stream_id": stream_id,
        },
        task_id=task_id,
    )

    t_pub = time.monotonic()
    produced = 0
    stop_reason = "timeout"
    ingest_ms = 0
    try:
        produced, stop_reason, ingest_ms = await dispatch_scheduled_ingest(
            run_id=run_id,
            thread_id=thread_id,
            stream_id=stream_id,
            node_id=node_id,
            task_id=task_id,
            pub_task_id=pub_task_id,
            task_name="MOCK_RUNNER_CONCURRENCY",
            token_per_sec=token_per_sec,
            timeout_secs=float(timeout_secs),
        )
    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, pub_task_id, "MOCK_RUNNER_CONCURRENCY")
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        # Delete the scheduler state and done_key so stale keys do not accumulate.
        # The done_key lives on a shard-routed client; sched state is on shard 0.
        from backend.db.redis.session.stream_sched import delete_stream  # noqa: PLC0415
        from backend.db.redis.router import get_redis_router  # noqa: PLC0415
        _done_key = f"fin:stream:ingest:done:{stream_id}"
        _shard_client = get_redis_router().get_client_for_stream(stream_id)
        await _shard_client.delete(_done_key)
        await delete_stream(run_id, stream_id)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception(
            "[concurrency_task] ingest error stream_id=%s task_id=%s thread_id=%s: %s",
            stream_id, task_id, thread_id, exc,
        )
        await fail_task(
            thread_id, pub_task_id, "MOCK_RUNNER_CONCURRENCY",
            str(exc), error_code=STREAM_PUBLISH_FAILED,
        )
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms)
        raise

    pub_ms = int((time.monotonic() - t_pub) * 1000)
    tps_val = produced / max(pub_ms / 1000, 0.001)

    await emit_ingest_complete(thread_id, stream_id, node_id, task_id, produced, stop_reason, ingest_ms)
    await complete_task(
        thread_id, pub_task_id, "MOCK_RUNNER_CONCURRENCY",
        {"total_published": produced, "pub_ms": pub_ms, "tps": round(tps_val, 2)},
    )

    if stop_reason in ("completed", "stable"):
        await emit_stream_complete(thread_id, stream_id, node_id, task_id, produced, tps_val, ingest_ms)
    else:
        await emit_stream_stopped(
            thread_id, stream_id, node_id, task_id, timeout_secs,
            total_published=produced, ingest_ms=ingest_ms,
        )

    total_elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    result = MockTaskResult(
        pub_task_id=pub_task_id,
        task_id=task_id,
        produced=produced,
        tps=round(tps_val, 2),
        result_str=(
            f"Stream (concurrency) done. "
            f"Produced: {produced} ({stop_reason}), Pub: {pub_ms}ms, TPS: {tps_val:.1f}"
        ),
    )
    await finish_node_execution(node_execution_id, result.as_node_output(), total_elapsed_ms)

    await publish_completion(
        provider="mock",
        model="mock",
        thread_id=thread_id,
        task_name="MOCK_RUNNER_CONCURRENCY",
        node_name=_NODE_NAME,
        completion_tokens=produced,
        latency_ms=ingest_ms,
        thinking=f"[mock -- {max(produced - 2, 0)} tokens]",
        answer=f"stream_{thread_id}",
    )

    logger.info(
        "[concurrency_task] done produced=%d stop_reason=%s pub_ms=%d tps=%.1f"
        " stream_id=%s task_id=%s thread_id=%s",
        produced, stop_reason, pub_ms, tps_val, stream_id, task_id, thread_id,
    )
    return result


__all__ = ["run_concurrency_task"]
