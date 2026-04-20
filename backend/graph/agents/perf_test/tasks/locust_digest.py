"""locust_digest — consume the perf stream and emit a locust_complete SSE event.

When ``pub_mode == "locust"`` the perf_test_streamer node calls
:func:`run_locust_digest` instead of the browser pub path.  This function
XREADs from ``fin:perf:{thread_id}``, counts every non-sentinel entry, then
emits a ``locust_complete`` SSE event so the frontend grid can update.

No per-token SSE events are emitted in locust mode — the browser grid tracks
only the final summary (total tokens consumed + throughput).  This mirrors
Locust's own measurement approach: submit → measure → report.
"""

from __future__ import annotations

import asyncio
import logging
import time

from backend.graph.agents.perf_test.celery_ingest.config import (
    PERF_INGEST_SENTINEL_FIELD,
    PERF_INGEST_SENTINEL_VALUE,
    PERF_INGEST_STREAM_PREFIX,
    PERF_PUB_READ_BATCH_SIZE,
)
from backend.graph.agents.perf_test.tasks.fanout_to_streams import _get_client
from backend.sse_notifications.perf_test.notifications import emit_locust_complete

logger = logging.getLogger(__name__)


async def run_locust_digest(
    thread_id: str,
) -> tuple[int, float]:
    """Drain ``fin:perf:{thread_id}`` and emit a ``locust_complete`` SSE event.

    Reads all tokens written by :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest`
    from the Redis stream without forwarding them to the browser SSE channel.
    Stops when the sentinel entry is encountered.  After draining, emits
    ``locust_complete`` so the frontend perf-test grid receives a single
    aggregate update.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Tuple ``(consumed, tps)`` — total tokens consumed and achieved
        throughput in tokens per second.
    """
    client = await _get_client()
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"
    last_id = "0-0"
    consumed = 0
    t_start = time.monotonic()

    logger.info("[locust_digest] start thread_id=%s", thread_id)

    while True:
        results = await client.xread(
            streams={stream: last_id},
            count=PERF_PUB_READ_BATCH_SIZE,
        )
        if not results:
            break
        _, messages = results[0]
        for msg_id, fields in messages:
            last_id = msg_id
            if fields.get(PERF_INGEST_SENTINEL_FIELD) == PERF_INGEST_SENTINEL_VALUE:
                # Sentinel reached — drain complete.
                elapsed = time.monotonic() - t_start
                digest_ms = int(elapsed * 1000)
                tps = consumed / max(elapsed, 0.001)
                logger.info(
                    "[locust_digest] complete consumed=%d tps=%.1f digest_ms=%d thread_id=%s",
                    consumed, tps, digest_ms, thread_id,
                )
                await emit_locust_complete(thread_id, consumed, round(tps, 2), digest_ms)
                return consumed, round(tps, 2)
            if fields.get("t"):
                consumed += 1
        # Yield between batches so the event loop stays responsive.
        await asyncio.sleep(0)

    # Stream ended without a sentinel (e.g. partial ingest due to timeout).
    elapsed = time.monotonic() - t_start
    digest_ms = int(elapsed * 1000)
    tps = consumed / max(elapsed, 0.001)
    logger.warning(
        "[locust_digest] no sentinel consumed=%d tps=%.1f thread_id=%s",
        consumed, tps, thread_id,
    )
    await emit_locust_complete(thread_id, consumed, round(tps, 2), digest_ms)
    return consumed, round(tps, 2)


__all__ = ["run_locust_digest"]
