"""perf_test_streamer — LangGraph node for streaming performance tests.

Two-phase architecture
----------------------

**Phase 1 — first-phase ingest** (``mock_ingest`` task)
    :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest_first_half`
    bulk-writes 95 % of ``total_tokens`` to ``fin:perf:{thread_id}``.
    When done the ``mock_ingest`` AgentTask is marked *completed* and a
    ``perf_ingest_complete`` event is sent so the frontend
    knows the first-phase milestone was reached and can set ``pub_start_ms``.

**Phase 2 — concurrent final-5 % ingest + adaptive read** (``mock_pub`` task)
    Two coroutines are launched via ``asyncio.gather`` *in the same Celery
    worker event loop*, ensuring write and read for the same streaming ID
    are co-located:

    * :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest_second_half`
      — bulk-writes the remaining tokens and appends the sentinel, updating a
      shared :class:`~backend.graph.agents.perf_test.tasks.fanout_to_streams._ConcurrentProgress`
      object with a rolling ingest TPS figure.

    * ``stream_perf_text_task`` consuming
      :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.dynamic_reader_gen`
      — adaptive batch sizing (1 → 3 → scaled to maintain 1.5× ingest TPS).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from datetime import datetime, timezone

from backend.graph.agents.task_keys import PERF_TEST_INGEST, PERF_TEST_PUB
from backend.graph.state import PerfTestState
from backend.graph.utils.execution_log import finish_node_execution, start_node_execution
from backend.db.redis.session.query_phase import set_query_phase
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    emit_perf_ingest_complete,
    emit_perf_test_complete,
    emit_perf_test_stopped,
    fail_task,
    stream_perf_text_task,
)
from backend.sse_notifications.query_lifecycle import emit_query_status

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _PerfTestOutput:
    """Structured result for the perf_test_streamer node."""

    total_tokens: int
    tps: float

    def as_dict(self) -> dict:
        """Return a plain dict for node execution log storage."""
        return {"total_tokens": self.total_tokens, "tps": self.tps}

_NODE_NAME: str = "perf_test_streamer"


async def perf_test_streamer(state: PerfTestState) -> dict:
    """Run the perf-test in throughput or concurrency mode.

    Throughput mode (default):
        Phase 1 (mock_ingest task): Ingests 95 % of tokens, marks completed,
        emits ``perf_ingest_half_complete``.
        Phase 2 (mock_pub task): Concurrent final-5 % ingest + adaptive pub.

    Concurrency mode:
        Skips Phase 1.  A single ``mock_pub`` task runs rate-limited ingest at
        ``token_per_sec`` tokens/s concurrently with the adaptive SSE publisher
        for ``timeout_secs`` seconds, then always ends with ``perf_test_stopped``.

    Args:
        state: PerfTestState with thread_id, total_tokens, timeout_secs, test_mode,
               and token_per_sec fields.

    Returns:
        Partial state update with result summary string.
    """
    # Lazy imports — only loaded when a perf test is actually triggered.
    from backend.graph.agents.perf_test.tasks.fanout_to_streams import (  # noqa: PLC0415
        _ConcurrentProgress,
        dynamic_reader_gen,
        run_ingest_first_half,
        run_ingest_second_half,
        run_rate_limited_ingest,
        register_concurrency_ingest,
        unregister_concurrency_ingest,
    )

    thread_id: str = state["thread_id"]
    total_tokens: int = state.get("total_tokens", 100_000)  # type: ignore[attr-defined]
    timeout_secs: int = state.get("timeout_secs", 60)  # type: ignore[attr-defined]
    test_mode: str = state.get("test_mode", "throughput")  # type: ignore[attr-defined]
    token_per_sec: int = state.get("token_per_sec", 500)  # type: ignore[attr-defined]

    started_at = datetime.now(timezone.utc)
    t0_node = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {
            "total_tokens": total_tokens,
            "timeout_secs": timeout_secs,
            "test_mode": test_mode,
            "token_per_sec": token_per_sec,
        },
        started_at,
    )

    # ------------------------------------------------------------------
    # Concurrency mode: single phase — rate-limited ingest + pub
    # ------------------------------------------------------------------
    if test_mode == "concurrency":
        await set_query_phase(thread_id, "digesting")
        await emit_query_status(thread_id, "digesting")

        progress = _ConcurrentProgress()
        pub_task_id = await create_task(
            thread_id, PERF_TEST_PUB, node_execution_id, provider="mock"
        )
        logger.info(
            "[perf_test_streamer] concurrency mode start token_per_sec=%d "
            "timeout_secs=%d thread_id=%s",
            token_per_sec, timeout_secs, thread_id,
        )

        t_pub = time.monotonic()
        published = 0
        stop_reason = "timeout"

        register_concurrency_ingest(thread_id, progress)
        try:
            ingest_result, pub_result = await asyncio.gather(
                run_rate_limited_ingest(
                    thread_id, token_per_sec, float(timeout_secs), t0_node, progress
                ),
                stream_perf_text_task(
                    thread_id, pub_task_id, PERF_TEST_PUB,
                    dynamic_reader_gen(thread_id, progress),
                ),
            )
            produced, stop_reason = ingest_result
            published = pub_result

        except (asyncio.CancelledError, TaskCancelledSignal):
            unregister_concurrency_ingest(thread_id)
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            await cancel_task(thread_id, pub_task_id, PERF_TEST_PUB)
            await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
            raise asyncio.CancelledError()
        except Exception as exc:
            unregister_concurrency_ingest(thread_id)
            elapsed_ms = int((time.monotonic() - t0_node) * 1000)
            logger.exception(
                "[perf_test_streamer] concurrency error thread_id=%s: %s", thread_id, exc
            )
            await fail_task(thread_id, pub_task_id, PERF_TEST_PUB, str(exc))
            await finish_node_execution(
                node_execution_id, {"error": str(exc)[:500]}, elapsed_ms
            )
            raise

        unregister_concurrency_ingest(thread_id)

        pub_ms = int((time.monotonic() - t_pub) * 1000)
        tps_val = published / max(pub_ms / 1000, 0.001)
        await complete_task(
            thread_id, pub_task_id, PERF_TEST_PUB,
            {"total_published": published, "pub_ms": pub_ms, "tps": round(tps_val, 2)},
        )
        # Emit perf_test_complete when the frontend signalled stability (clean
        # early exit); emit perf_test_stopped for the normal timeout path.
        if stop_reason == "stable":
            await emit_perf_test_complete(thread_id, published, tps_val)
        else:
            await emit_perf_test_stopped(thread_id, timeout_secs, total_published=published)

        total_elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await finish_node_execution(
            node_execution_id,
            _PerfTestOutput(total_tokens=published, tps=round(tps_val, 2)).as_dict(),
            total_elapsed_ms,
        )
        logger.info(
            "[perf_test_streamer] concurrency done published=%d pub_ms=%d tps=%.1f thread_id=%s",
            published, pub_ms, tps_val, thread_id,
        )
        return {
            "result": (
                f"Concurrency test done. Published: {published}, "
                f"Pub: {pub_ms}ms, TPS: {tps_val:.1f}"
            )
        }

    # ------------------------------------------------------------------
    # Phase 1: first-half INGEST
    # ------------------------------------------------------------------
    await set_query_phase(thread_id, "ingesting")
    await emit_query_status(thread_id, "ingesting")

    ingest_task_id = await create_task(
        thread_id, PERF_TEST_INGEST, node_execution_id, provider="mock"
    )
    logger.info(
        "[perf_test_streamer] phase1 ingest_task=%d total_tokens=%d "
        "timeout_secs=%d thread_id=%s",
        ingest_task_id, total_tokens, timeout_secs, thread_id,
    )

    try:
        produced, first_stop_reason = await run_ingest_first_half(
            thread_id, total_tokens, float(timeout_secs)
        )
    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, ingest_task_id, PERF_TEST_INGEST)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception(
            "[perf_test_streamer] phase1 ingest error thread_id=%s: %s", thread_id, exc
        )
        await fail_task(thread_id, ingest_task_id, PERF_TEST_INGEST, str(exc))
        await finish_node_execution(
            node_execution_id, {"error": str(exc)[:500]}, elapsed_ms
        )
        raise

    t_ingest_ms = int((time.monotonic() - t0_node) * 1000)
    await complete_task(
        thread_id,
        ingest_task_id,
        PERF_TEST_INGEST,
        {
            "total_generated": produced,
            "stop_reason": first_stop_reason,
        },
    )
    await emit_perf_ingest_complete(
        thread_id,
        ingest_ms=t_ingest_ms,
        produced=produced,
        stop_reason=first_stop_reason,
    )
    logger.info(
        "[perf_test_streamer] phase1 done produced=%d stop_reason=%s thread_id=%s",
        produced, first_stop_reason, thread_id,
    )

    # Bail early if phase 1 already hit the global timeout.
    if first_stop_reason == "timeout":
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await emit_perf_test_stopped(thread_id, timeout_secs)
        await finish_node_execution(
            node_execution_id,
            _PerfTestOutput(total_tokens=produced, tps=0.0).as_dict(),
            elapsed_ms,
        )
        return {
            "result": f"Perf test timeout at phase1. Generated: {produced} ({first_stop_reason})"
        }

    # ------------------------------------------------------------------
    # Phase 2: concurrent second-half INGEST + PUB
    # ------------------------------------------------------------------
    await set_query_phase(thread_id, "digesting")
    await emit_query_status(thread_id, "digesting")

    progress = _ConcurrentProgress(produced=produced)
    task_key = PERF_TEST_PUB
    pub_task_id = await create_task(
        thread_id, task_key, node_execution_id, provider="mock"
    )
    logger.info(
        "[perf_test_streamer] phase2 start pub_task=%d thread_id=%s",
        pub_task_id, thread_id,
    )

    t_pub = time.monotonic()
    published = 0
    second_stop_reason = "completed"

    async def _ingest_second() -> tuple[int, str]:
        """Run second-half ingest; propagates CancelledError cleanly."""
        return await run_ingest_second_half(
            thread_id,
            produced,
            total_tokens,
            float(timeout_secs),
            t0_node,
            progress,
        )

    async def _browser_pub() -> int:
        """Consume dynamic_reader_gen and emit perf_token_batch SSE events."""
        return await stream_perf_text_task(
            thread_id,
            pub_task_id,
            task_key,
            dynamic_reader_gen(thread_id, progress),
        )

    try:
        ingest_result, pub_result = await asyncio.gather(
            _ingest_second(), _browser_pub()
        )
        additional_produced, second_stop_reason = ingest_result
        published = pub_result

    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, pub_task_id, task_key)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception(
            "[perf_test_streamer] phase2 error thread_id=%s: %s", thread_id, exc
        )
        await fail_task(thread_id, pub_task_id, task_key, str(exc))
        await finish_node_execution(
            node_execution_id, {"error": str(exc)[:500]}, elapsed_ms
        )
        raise

    pub_ms = int((time.monotonic() - t_pub) * 1000)
    total_produced = produced + additional_produced
    stop_reason = second_stop_reason if second_stop_reason != "completed" else first_stop_reason
    # Treat "half_done" (phase-1 normal finish) as "completed" for the final status.
    # Guard against any legacy "phase1_done" value that may appear in old workers.
    final_stop = "completed" if stop_reason in ("half_done", "phase1_done") else stop_reason

    tps_val = published / max(pub_ms / 1000, 0.001)
    await complete_task(
        thread_id,
        pub_task_id,
        task_key,
        {
            "total_published": published,
            "total_produced": total_produced,
            "pub_ms": pub_ms,
            "tps": round(tps_val, 2),
        },
    )
    if published < total_tokens:
        logger.warning(
            "[perf_test_streamer] short publish published=%d total=%d "
            "final_stop=%s thread_id=%s",
            published, total_tokens, final_stop, thread_id,
        )
    if final_stop == "completed":
        await emit_perf_test_complete(thread_id, published, tps_val)
    else:
        await emit_perf_test_stopped(thread_id, timeout_secs, total_published=published)

    total_elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    output = _PerfTestOutput(
        total_tokens=published,
        tps=round(tps_val, 2),
    )
    await finish_node_execution(node_execution_id, output.as_dict(), total_elapsed_ms)

    result = (
        f"Perf test done. "
        f"Generated: {total_produced} ({final_stop}), "
        f"Published: {published}, Pub: {pub_ms}ms, TPS: {tps_val:.1f}"
    )
    logger.info(
        "[perf_test_streamer] done total_produced=%d published=%d "
        "final_stop=%s pub_ms=%d tps=%.1f thread_id=%s",
        total_produced, published, final_stop, pub_ms, tps_val, thread_id,
    )
    return {"result": result}

