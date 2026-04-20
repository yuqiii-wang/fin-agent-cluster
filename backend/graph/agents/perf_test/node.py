"""perf_test_streamer — LangGraph node for streaming performance tests.

Two-phase sequential architecture:

* **PERF_TEST_INGEST** (``mock_ingest`` task) — PerfIngest Celery app
  bulk-writes tokens to ``fin:perf:{thread_id}`` Redis stream in batches
  via a Redis pipeline.  The Celery task self-chains (drain-first) until all
  *total_tokens* are produced or *timeout_secs* elapses.  The node awaits
  completion via Redis BLPOP (no polling).  Ingest stats (total_generated,
  stop_reason) are recorded in the task's completion output.

* **PERF_TEST_PUB** (``mock_pub`` task) — **Created only after ingest
  completes**.  Reads from ``fin:perf:{thread_id}`` via
  :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.perf_stream_reader_gen`
  and emits ``perf_token`` SSE events via
  :func:`~backend.sse_notifications.stream_perf_text_task`.  Publish stats
  (total_published, TPS) appear in its completion output.

The sequential design means the UI task sidebar shows two distinct rows:
ingest first (completed), then pub (in-progress → completed).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from backend.graph.agents.perf_test.models.output import PerfTestOutput
from backend.graph.agents.perf_test.tasks.fanout_to_streams import (
    perf_stream_reader_gen,
    run_ingest,
)
from backend.graph.agents.perf_test.tasks.locust_digest import run_locust_digest
from backend.graph.agents.task_keys import PERF_TEST_INGEST, PERF_TEST_LOCUST, PERF_TEST_PUB
from backend.graph.state import PerfTestState
from backend.graph.utils.execution_log import finish_node_execution, start_node_execution
from backend.db.redis.query_phase import set_query_phase
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    emit_locust_complete,
    emit_perf_ingest_complete,
    emit_perf_test_complete,
    emit_perf_test_stopped,
    fail_task,
    stream_perf_text_task,
)
from backend.sse_notifications.perf_test import emit_query_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "perf_test_streamer"


async def perf_test_streamer(state: PerfTestState) -> dict:
    """Run the perf-test: bulk ingest via Celery then publish via SSE.

    Phase 1 (ingest):
        Creates ``mock_ingest`` AgentTask, dispatches PerfIngest Celery app to
        bulk-write all tokens to the per-session Redis stream, awaits
        completion, then marks the task completed.

    Phase 2 (pub):
        Creates ``mock_pub`` AgentTask **after** ingest is done, reads from the
        Redis stream via :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.perf_stream_reader_gen`,
        and emits ``perf_token`` SSE events.

    Args:
        state: PerfTestState with thread_id, total_tokens, timeout_secs, and
               pub_mode fields.

    Returns:
        Partial state update with result summary string.
    """
    thread_id: str = state["thread_id"]
    total_tokens: int = state.get("total_tokens", 100_000)  # type: ignore[attr-defined]
    timeout_secs: int = state.get("timeout_secs", 60)  # type: ignore[attr-defined]
    pub_mode: str = state.get("pub_mode", "browser")  # type: ignore[attr-defined]

    started_at = datetime.now(timezone.utc)
    t0_node = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {
            "total_tokens": total_tokens,
            "timeout_secs": timeout_secs,
        },
        started_at,
    )

    # ------------------------------------------------------------------
    # Phase 1: INGEST
    # ------------------------------------------------------------------
    await set_query_phase(thread_id, "ingesting")
    await emit_query_status(thread_id, "ingesting")

    ingest_task_id = await create_task(
        thread_id, PERF_TEST_INGEST, node_execution_id, provider="mock"
    )
    logger.info(
        "[perf_test_streamer] ingest start ingest_task=%d "
        "total_tokens=%d timeout_secs=%d thread_id=%s",
        ingest_task_id, total_tokens, timeout_secs, thread_id,
    )

    t_ingest = time.monotonic()
    try:
        produced, stop_reason = await run_ingest(
            thread_id, total_tokens, float(timeout_secs)
        )
    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, ingest_task_id, PERF_TEST_INGEST)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception("[perf_test_streamer] ingest error thread_id=%s: %s", thread_id, exc)
        await fail_task(thread_id, ingest_task_id, PERF_TEST_INGEST, str(exc))
        await finish_node_execution(
            node_execution_id, {"error": str(exc)[:500]}, elapsed_ms
        )
        raise

    ingest_ms = int((time.monotonic() - t_ingest) * 1000)
    await complete_task(
        thread_id,
        ingest_task_id,
        PERF_TEST_INGEST,
        {
            "total_generated": produced,
            "stop_reason": stop_reason,
            "ingest_ms": ingest_ms,
        },
    )
    await emit_perf_ingest_complete(thread_id, ingest_ms, produced, stop_reason)
    logger.info(
        "[perf_test_streamer] ingest done produced=%d stop_reason=%s "
        "ingest_ms=%d thread_id=%s",
        produced, stop_reason, ingest_ms, thread_id,
    )

    # ------------------------------------------------------------------
    # Phase 2: PUB or LOCUST DIGEST  (created after ingest)
    # ------------------------------------------------------------------
    await set_query_phase(thread_id, "sending")
    await emit_query_status(thread_id, "sending")

    if pub_mode == "locust":
        # Locust digest: drain stream without emitting per-token SSE events.
        locust_task_id = await create_task(
            thread_id, PERF_TEST_LOCUST, node_execution_id, provider="mock"
        )
        logger.info(
            "[perf_test_streamer] locust_digest start task=%d thread_id=%s",
            locust_task_id, thread_id,
        )
        t_pub = time.monotonic()
        try:
            consumed, tps = await run_locust_digest(thread_id)
        except (asyncio.CancelledError, TaskCancelledSignal):
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            await cancel_task(thread_id, locust_task_id, PERF_TEST_LOCUST)
            await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
            raise asyncio.CancelledError()
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            logger.exception("[perf_test_streamer] locust_digest error thread_id=%s: %s", thread_id, exc)
            await fail_task(thread_id, locust_task_id, PERF_TEST_LOCUST, str(exc))
            await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms)
            raise

        pub_ms = int((time.monotonic() - t_pub) * 1000)
        published = consumed
        await complete_task(
            thread_id,
            locust_task_id,
            PERF_TEST_LOCUST,
            {
                "consumed": consumed,
                "digest_ms": pub_ms,
                "tps": round(tps, 2),
            },
        )
        if stop_reason == "completed":
            await emit_perf_test_complete(thread_id, consumed, tps)
        else:
            await emit_perf_test_stopped(thread_id, timeout_secs)
    else:
        # Browser pub: read stream and emit perf_token SSE events.
        pub_task_id = await create_task(
            thread_id, PERF_TEST_PUB, node_execution_id, provider="mock"
        )
        logger.info(
            "[perf_test_streamer] pub start pub_task=%d thread_id=%s",
            pub_task_id, thread_id,
        )

        t_pub = time.monotonic()
        try:
            published = await stream_perf_text_task(
                thread_id,
                pub_task_id,
                PERF_TEST_PUB,
                perf_stream_reader_gen(thread_id),
            )
        except TaskCancelledSignal:
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            await cancel_task(thread_id, pub_task_id, PERF_TEST_PUB)
            await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
            raise asyncio.CancelledError()
        except asyncio.CancelledError:
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            await cancel_task(thread_id, pub_task_id, PERF_TEST_PUB)
            await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
            raise
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            logger.exception("[perf_test_streamer] pub error thread_id=%s: %s", thread_id, exc)
            await fail_task(thread_id, pub_task_id, PERF_TEST_PUB, str(exc))
            await finish_node_execution(
                node_execution_id, {"error": str(exc)[:500]}, elapsed_ms
            )
            raise

        pub_ms = int((time.monotonic() - t_pub) * 1000)
        tps = published / max(pub_ms / 1000, 0.001)

        await complete_task(
            thread_id,
            pub_task_id,
            PERF_TEST_PUB,
            {
                "total_published": published,
                "pub_ms": pub_ms,
                "tps": round(tps, 2),
            },
        )

        if stop_reason == "completed":
            await emit_perf_test_complete(thread_id, published, tps)
        else:
            await emit_perf_test_stopped(thread_id, timeout_secs)

    total_elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    output = PerfTestOutput(
        total_tokens=published,
        tps=round(tps, 2),
    )
    await finish_node_execution(node_execution_id, output.model_dump(), total_elapsed_ms)

    result = (
        f"Perf test done. "
        f"Generated: {produced} ({stop_reason}), "
        f"Published: {published}, Pub: {pub_ms}ms, TPS: {tps:.1f}"
    )
    logger.info(
        "[perf_test_streamer] done produced=%d published=%d "
        "stop_reason=%s pub_ms=%d tps=%.1f thread_id=%s",
        produced, published, stop_reason, pub_ms, tps, thread_id,
    )
    return {"result": result}

