"""Celery worker — throughput token ingest task.

Bulk-writes all tokens to ``fin:llm:tokens`` as fast as possible
(no rate limiting).  Ingest and delivery are **sequential**:

  ingesting -> (all tokens written) -> digesting -> browser receives all tokens

Completion trigger: all ``total_tokens`` written (token-bounded).  The FastAPI
dispatcher awaits the Celery result via ``async_result.get()`` in an executor
thread since ingest completes quickly and the result is needed immediately
to emit the ``digesting`` phase transition.

This task is completely isolated from the concurrency / fanout path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any

from backend.streaming.celery_app import celery_app
from backend.streaming.streams import STREAM_TOKEN, xadd_sharded

logger = logging.getLogger(__name__)

#: Exponential flush threshold ceiling for throughput mode.
_BATCH_SIZE: int = 1024


@celery_app.task(
    name="backend.streaming.workers.throughput.run_stream_ingest_throughput",
    bind=False,
    queue="stream:ingest",
    acks_late=True,
)
def run_stream_ingest_throughput(
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    pub_task_id: str,
    task_name: str,
    total_tokens: int,
    timeout_secs: float,
) -> dict[str, Any]:
    """Throughput ingest: bulk-write all tokens as fast as possible.

    Args:
        thread_id:      LangGraph thread UUID.
        stream_id:      Celery ingest run UUID.
        node_id:        Node execution UUID.
        task_id:      Task invocation UUID.
        pub_task_id:  Pre-created ``fin_agents.tasks`` row UUID (PK).
        task_name:       Full dot-separated task key.
        total_tokens:   Target token budget.
        timeout_secs:   Hard deadline in seconds.

    Returns:
        Dict with keys ``produced``, ``stop_reason``, ``ingest_ms``.
    """
    return asyncio.run(
        _ingest_throughput(
            thread_id, stream_id, node_id, task_id,
            pub_task_id, task_name, total_tokens, timeout_secs,
        )
    )


async def _ingest_throughput(
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    pub_task_id: str,
    task_name: str,
    total_tokens: int,
    timeout_secs: float,
) -> dict[str, Any]:
    """Write all tokens to ``fin:llm:tokens`` as fast as possible.

    Args:
        thread_id:      LangGraph thread UUID.
        stream_id:      Celery ingest run UUID.
        node_id:        Node execution UUID.
        task_id:      Task invocation UUID.
        pub_task_id:  Task row UUID (PK).
        task_name:       Full task key string.
        total_tokens:   Token budget.
        timeout_secs:   Hard deadline.

    Returns:
        Dict with ``produced``, ``stop_reason``, ``ingest_ms``.
    """
    from backend.llm.providers.mock import get_mock_llm  # noqa: PLC0415
    from backend.graph.governance import register_stream, deregister_stream  # noqa: PLC0415

    await register_stream(thread_id, node_id, task_id, stream_id)

    mock_llm = get_mock_llm(
        thread_id=thread_id,
        timeout_secs=timeout_secs,
        total_tokens=total_tokens,
        stream_id=stream_id,
    )

    produced = 0
    stop_reason = "completed"
    t_start = time.monotonic()
    node_name = task_name.split(".")[0]
    token_window: deque[str] = deque(maxlen=10)
    flush_threshold = 1
    pending_batch: list[str] = []

    logger.info(
        "[stream_ingest] throughput start pid=%d total=%d timeout=%.1fs stream_id=%s thread_id=%s",
        os.getpid(), total_tokens, timeout_secs, stream_id, thread_id,
    )

    try:
        async for chunk in mock_llm._astream([]):
            if time.monotonic() - t_start > timeout_secs:
                stop_reason = "timeout"
                break
            token: str = chunk.message.content
            if token:
                pending_batch.append(token)
                token_window.append(token.strip())
                produced += 1
            if len(pending_batch) >= flush_threshold:
                await _flush_batch(
                    thread_id, pub_task_id, task_name, node_name,
                    len(pending_batch), list(token_window),
                    stream_id=stream_id,
                )
                pending_batch = []
                flush_threshold = min(flush_threshold * 2, _BATCH_SIZE)

        ingest_ms = int((time.monotonic() - t_start) * 1000)
        if pending_batch:
            await _flush_batch(
                thread_id, pub_task_id, task_name, node_name,
                len(pending_batch), list(token_window),
                ingest_ms=ingest_ms,
                stream_id=stream_id,
            )
    finally:
        await deregister_stream(thread_id, node_id, task_id, stream_id)

    logger.info(
        "[stream_ingest] throughput done produced=%d stop_reason=%s ingest_ms=%d stream_id=%s thread_id=%s",
        produced, stop_reason, ingest_ms, stream_id, thread_id,
    )
    return {"produced": produced, "stop_reason": stop_reason, "ingest_ms": ingest_ms}


async def _flush_batch(
    thread_id: str,
    pub_task_id: str,
    task_name: str,
    node_name: str,
    count: int,
    recent_tokens: list[str],
    ingest_ms: int | None = None,
    stream_id: str = "",
) -> None:
    """XADD one ``token_batch`` entry to ``fin:llm:tokens``.

    Args:
        thread_id:      LangGraph thread UUID.
        pub_task_id:  Task row UUID (PK).
        task_name:       Full task key string.
        node_name:      Agent node name prefix.
        count:          Number of tokens in this batch.
        recent_tokens:  Rolling window of last 10 token strings.
        ingest_ms:      When set, embedded in the last batch.
        stream_id:      Celery ingest run UUID (for log correlation).
    """
    event: dict[str, Any] = {
        "event": "token_batch",
        "task_id": pub_task_id,
        "node_name": node_name,
        "task_name": task_name,
        "count": count,
        "recent_tokens": recent_tokens,
    }
    if ingest_ms is not None:
        event["ingest_ms"] = ingest_ms
    payload_value = json.dumps({"channel": f"thread:{thread_id}", "data": event})
    try:
        await xadd_sharded(
            thread_id,
            STREAM_TOKEN,
            {"method": "publish", "payload": payload_value},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[stream_ingest] xadd failed count=%d stream_id=%s thread_id=%s: %s",
            count, stream_id, thread_id, exc,
        )


__all__ = ["run_stream_ingest_throughput"]
