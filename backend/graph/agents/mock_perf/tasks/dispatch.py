"""dispatch -- dispatch utility for throughput token ingest via Celery.

Single dispatch strategy:

* :func:`dispatch_throughput_ingest` — token-bounded completion.  Awaits the
  Celery result via ``async_result.get()`` in an executor thread; acceptable
  since throughput ingest completes quickly (write speed is not rate-limited).

Concurrency-mode streams use :func:`~coordinator.dispatch_scheduled_ingest`
directly — the fanout coordinator manages all streams in a run_id batch.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Throughput constants
# ---------------------------------------------------------------------------

_THROUGHPUT_RESULT_GET_MAX_RETRIES: int = 3
_THROUGHPUT_RESULT_GET_RETRY_DELAY_S: float = 0.5
# Throughput ingest is token-bounded (not rate-limited) so task runtime is
# short.  Allow timeout_secs for worst-case queue wait + 60 s buffer.
_THROUGHPUT_RESULT_GET_TIMEOUT_BUFFER_S: int = 60

async def dispatch_throughput_ingest(
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    pub_task_id: str,
    task_name: str,
    total_tokens: int,
    timeout_secs: float,
) -> tuple[int, str, int]:
    """Dispatch a throughput ingest task and await its result.

    Args:
        thread_id:      LangGraph thread UUID.
        stream_id:      Celery ingest run UUID.
        node_id:        Node execution UUID.
        task_id:      Task invocation UUID.
        pub_task_id:  Pre-created task row UUID (PK).
        task_name:       Full dot-separated task key.
        total_tokens:   Target token budget.
        timeout_secs:   Hard deadline in seconds.

    Returns:
        Tuple ``(produced, stop_reason, ingest_ms)``.

    Raises:
        RuntimeError: When ingest fails after all retries.
    """
    from backend.streaming.workers.throughput import run_stream_ingest_throughput  # noqa: PLC0415

    loop = asyncio.get_running_loop()
    async_result = run_stream_ingest_throughput.delay(
        thread_id=thread_id,
        stream_id=stream_id,
        node_id=node_id,
        task_id=task_id,
        pub_task_id=pub_task_id,
        task_name=task_name,
        total_tokens=total_tokens,
        timeout_secs=timeout_secs,
    )

    result: dict[str, Any] | None = None
    last_exc: Exception | None = None
    get_timeout = int(timeout_secs) + _THROUGHPUT_RESULT_GET_TIMEOUT_BUFFER_S
    for attempt in range(1, _THROUGHPUT_RESULT_GET_MAX_RETRIES + 1):
        try:
            result = await loop.run_in_executor(
                None,
                lambda: async_result.get(timeout=get_timeout),
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "[dispatch_throughput_ingest] attempt=%d/%d error=%s stream_id=%s thread_id=%s",
                attempt, _THROUGHPUT_RESULT_GET_MAX_RETRIES, exc, stream_id, thread_id,
            )
            if attempt < _THROUGHPUT_RESULT_GET_MAX_RETRIES:
                await asyncio.sleep(_THROUGHPUT_RESULT_GET_RETRY_DELAY_S)

    if result is None:
        raise RuntimeError(
            f"throughput ingest failed after {_THROUGHPUT_RESULT_GET_MAX_RETRIES} retries: {last_exc}"
        )

    produced: int = result.get("produced", 0)
    stop_reason: str = result.get("stop_reason", "completed")
    ingest_ms: int = result.get("ingest_ms", 0)
    logger.info(
        "[dispatch_throughput_ingest] produced=%d stop_reason=%s ingest_ms=%d stream_id=%s thread_id=%s",
        produced, stop_reason, ingest_ms, stream_id, thread_id,
    )
    return produced, stop_reason, ingest_ms


__all__ = ["dispatch_throughput_ingest"]
