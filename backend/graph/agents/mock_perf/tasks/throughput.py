"""throughput -- run_throughput_task wraps the full throughput stream lifecycle.

Throughput mode
---------------
Celery ingest bulk-writes ``token_batch`` events to ``fin:llm:tokens`` as fast
as possible (no rate limiting).  All tokens are written before Centrifugo
delivers them to the browser, so the two phases are sequential:

  **ingesting** -> (ingest done) -> **digesting** -> browser receives all tokens
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


async def run_throughput_task(
    thread_id: str,
    total_tokens: int,
    timeout_secs: int,
    node_execution_id: int,
    t0_node: float,
    node_id: str,
    task_id: str,
    stream_id: str,
    task_name_override: str | None = None,
) -> MockTaskResult:
    """Wrap the throughput stream lifecycle: ingest -> phase transition -> complete.

    Dispatches a Celery ``run_stream_ingest_throughput`` task, emits
    all lifecycle SSE events, and records node execution telemetry.

    The ``digesting`` phase is emitted **after** ingest completes so the phase
    accurately reflects "pure delivery" rather than "writing in progress".

    Args:
        thread_id:          LangGraph thread UUID.
        total_tokens:       Target token count for the ingest run.
        timeout_secs:       Hard deadline in seconds.
        node_execution_id:  DB row ID from :func:`start_node_execution`.
        t0_node:            ``time.monotonic()`` captured at node entry.
        node_id:            Node execution UUID.
        task_id:          Task invocation UUID (task-level identity).
        stream_id:          Streaming session UUID (Celery ingest run).
        task_name_override:  Override the DB task key (e.g. ``MOCK_MERGE`` for
                            the merge node).  Defaults to ``"MOCK_RUNNER_THROUGHPUT"``.

    Returns:
        :class:`MockTaskResult` with task ID, task_id, produced count, TPS, and summary.

    Raises:
        asyncio.CancelledError: When the task is cancelled (already cleaned up).
        Exception:              On ingest failure (already cleaned up).
    """
    from backend.graph.agents.mock_perf.tasks.dispatch import dispatch_throughput_ingest  # noqa: PLC0415

    task_name = task_name_override or "MOCK_RUNNER_THROUGHPUT"

    await set_query_phase(thread_id, "ingesting")
    await emit_query_status(thread_id, "ingesting", stream_id=stream_id)

    # Use the caller-supplied task_id as the primary key so that the "started"
    # and "completed" SSE events carry the same task_id.  Generating a new
    # uuid here (the old behaviour) caused the two events to have different
    # task_ids, which the frontend interpreted as two separate tasks.
    pub_task_id = await create_task(
        thread_id,
        task_name,
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
    stop_reason = "completed"
    ingest_ms = 0
    try:
        produced, stop_reason, ingest_ms = await dispatch_throughput_ingest(
            thread_id=thread_id,
            stream_id=stream_id,
            node_id=node_id,
            task_id=task_id,
            pub_task_id=pub_task_id,
            task_name=task_name,
            total_tokens=total_tokens,
            timeout_secs=float(timeout_secs),
        )
    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, pub_task_id, task_name)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception(
            "[throughput_task] ingest error stream_id=%s task_id=%s thread_id=%s: %s",
            stream_id, task_id, thread_id, exc,
        )
        await fail_task(
            thread_id, pub_task_id, task_name,
            str(exc), error_code=STREAM_PUBLISH_FAILED,
        )
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms)
        raise

    # Ingest complete -- transition to digesting phase.
    await set_query_phase(thread_id, "digesting")
    await emit_query_status(thread_id, "digesting")

    pub_ms = int((time.monotonic() - t_pub) * 1000)
    tps_val = produced / max(pub_ms / 1000, 0.001)

    await emit_ingest_complete(thread_id, stream_id, node_id, task_id, produced, stop_reason, ingest_ms)
    await complete_task(
        thread_id, pub_task_id, task_name,
        {"total_published": produced, "pub_ms": pub_ms, "tps": round(tps_val, 2)},
    )

    if stop_reason == "completed":
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
            f"Stream (throughput) done. "
            f"Produced: {produced} ({stop_reason}), Pub: {pub_ms}ms, TPS: {tps_val:.1f}"
        ),
    )
    await finish_node_execution(node_execution_id, result.as_node_output(), total_elapsed_ms)

    await publish_completion(
        provider="mock",
        model="mock",
        thread_id=thread_id,
        task_name=task_name,
        node_name=_NODE_NAME,
        completion_tokens=produced,
        latency_ms=ingest_ms,
        thinking=f"[mock -- {max(produced - 2, 0)} tokens]",
        answer=f"stream_{thread_id}",
    )

    logger.info(
        "[throughput_task] done produced=%d stop_reason=%s pub_ms=%d tps=%.1f"
        " stream_id=%s task_id=%s thread_id=%s",
        produced, stop_reason, pub_ms, tps_val, stream_id, task_id, thread_id,
    )
    return result


__all__ = ["run_throughput_task"]
