"""merge_node — fan-in node that merges news + stats and runs the stream ingest/digest.

Node position in the pipeline:

    query_node → [news_node, stats_node] → merge_node → END

Durable-execution design
------------------------
``interrupt()`` fires first — establishing a checkpoint boundary.  All side
effects (UUID generation, DB tracking, Celery dispatch) live inside the
``@task``-decorated :func:`_run_merge_node` so they are checkpointed when the
task completes.  On resume, a completed ``_run_merge_node`` is *replayed* from
the checkpoint — never re-executed — which eliminates the duplicate-node-id
fork seen in the UI.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from langgraph.func import task
from langgraph.types import interrupt

from backend.graph.agents._shared.errors import MERGE_FAILED
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import (
    start_node_execution,
    update_node_execution_status,
)
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.sse_notifications.node import emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "merge"

_BASE_TOKENS: int = 5_000
_TOKENS_PER_ARTICLE: int = 200
_TOKENS_PER_STAT: int = 100
_MAX_TOKENS: int = 20_000
_INGEST_TIMEOUT_SECS: int = 30


def _compute_token_budget(news_articles: list[dict], stats_records: list[dict]) -> int:
    """Compute a token budget that scales with the volume of merged data."""
    budget = (
        _BASE_TOKENS
        + len(news_articles) * _TOKENS_PER_ARTICLE
        + len(stats_records) * _TOKENS_PER_STAT
    )
    return min(budget, _MAX_TOKENS)


@task
async def _run_merge_node(
    thread_id: str,
    parent_node_execution_id: int | None,
    news_articles: list[dict],
    stats_records: list[dict],
    symbol: str,
) -> dict:
    """All merge-node side effects: UUIDs, DB tracking, Celery dispatch, emit events.

    Wrapped in ``@task`` so the result is checkpointed on completion.
    On resume after a cancel, a completed task is replayed — never
    re-executed — keeping ``node_execution_id`` / ``node_id`` stable.
    """
    from backend.graph.agents.mock_perf.tasks.throughput import run_throughput_task  # noqa: PLC0415
    from backend.db.redis.session.query_phase import set_query_phase  # noqa: PLC0415
    from backend.sse_notifications.thread import emit_query_status  # noqa: PLC0415

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    stream_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    total_tokens = _compute_token_budget(news_articles, stats_records)

    logger.info(
        "[merge] symbol=%s articles=%d stat_records=%d tokens=%d thread_id=%s",
        symbol, len(news_articles), len(stats_records), total_tokens, thread_id,
    )

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {
            "article_count": len(news_articles),
            "stat_record_count": len(stats_records),
            "total_tokens": total_tokens,
            "node_id": node_id,
            "task_id": task_id,
            "stream_id": stream_id,
        },
        started_at,
        node_uuid=node_id,
        parent_node_execution_id=parent_node_execution_id,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    terminal_status = "completed"
    try:
        task_result = await run_throughput_task(
            thread_id=thread_id,
            total_tokens=total_tokens,
            timeout_secs=_INGEST_TIMEOUT_SECS,
            node_execution_id=node_execution_id,
            t0_node=t0,
            node_id=node_id,
            task_id=task_id,
            stream_id=stream_id,
            task_name_override="MERGE",
        )
    except asyncio.CancelledError:
        terminal_status = "cancelled"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise
    except Exception:
        terminal_status = "failed"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise

    # run_throughput_task calls finish_node_execution internally; only emit node status.
    await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)

    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_result.pub_task_id,
        "stream_id": stream_id,
        "result": task_result.result_str,
    }


async def merge_node(state: StreamRunState) -> dict:
    """LangGraph node: checkpoint via ``interrupt()`` then delegate to ``@task``.

    Reading state fields before ``interrupt()`` has no side effects and is
    safe on resume.  All DB writes / SSE emits are inside :func:`_run_merge_node`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` carrying
               ``news_articles`` and ``stats_records`` from upstream nodes.

    Returns:
        Partial state update with ``node_id``, ``task_id``, ``stream_id``,
        and ``result``.
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    news_articles: list[dict] = state.get("news_articles") or []
    stats_records: list[dict] = state.get("stats_records") or []
    symbol: str = (state.get("query_response") or {}).get("symbol", "?")

    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    return await _run_merge_node(
        thread_id, parent_node_execution_id, news_articles, stats_records, symbol,
    )


__all__ = ["merge_node"]

logger = logging.getLogger(__name__)

_NODE_NAME: str = "merge"

# Token budget for the merged ingest — represents the digest of news + stats.
# Scales with combined data size; capped to keep demos fast.
_BASE_TOKENS: int = 5_000
_TOKENS_PER_ARTICLE: int = 200
_TOKENS_PER_STAT: int = 100
_MAX_TOKENS: int = 20_000
_INGEST_TIMEOUT_SECS: int = 30


def _compute_token_budget(news_articles: list[dict], stats_records: list[dict]) -> int:
    """Compute a token budget that scales with the volume of merged data.

    Args:
        news_articles: Serialised news article dicts.
        stats_records: Serialised stats record dicts.

    Returns:
        Token budget capped at :data:`_MAX_TOKENS`.
    """
    budget = (
        _BASE_TOKENS
        + len(news_articles) * _TOKENS_PER_ARTICLE
        + len(stats_records) * _TOKENS_PER_STAT
    )
    return min(budget, _MAX_TOKENS)


async def merge_node(state: StreamRunState) -> dict:
    """Merge news + stats and run a throughput Celery stream ingest.

    Uses ``interrupt()`` as a step-approval checkpoint (replacing the former
    ``check_node_cancel`` Redis signal) then computes a token budget from the
    merged payload size and delegates to
    :func:`~backend.graph.agents.mock_perf.tasks.throughput.run_throughput_task`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` carrying
               ``news_articles`` and ``stats_records`` from upstream nodes.

    Returns:
        Partial state update with ``node_id``, ``task_id``, ``stream_id``,
        and ``result``.
    """
    from backend.graph.agents.mock_perf.tasks.throughput import run_throughput_task  # noqa: PLC0415
    from backend.db.redis.session.query_phase import set_query_phase  # noqa: PLC0415
    from backend.sse_notifications.thread import emit_query_status  # noqa: PLC0415

    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    news_articles: list[dict] = state.get("news_articles") or []
    stats_records: list[dict] = state.get("stats_records") or []
    query_response: dict = state.get("query_response") or {}

    # ── Step-approval interrupt (replaces check_node_cancel) ──────────────
    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    stream_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    total_tokens = _compute_token_budget(news_articles, stats_records)

    logger.info(
        "[merge] symbol=%s articles=%d stat_records=%d tokens=%d thread_id=%s",
        query_response.get("symbol", "?"),
        len(news_articles),
        len(stats_records),
        total_tokens,
        thread_id,
    )

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {
            "article_count": len(news_articles),
            "stat_record_count": len(stats_records),
            "total_tokens": total_tokens,
            "node_id": node_id,
            "task_id": task_id,
            "stream_id": stream_id,
        },
        started_at,
        node_uuid=node_id,
        parent_node_execution_id=parent_node_execution_id,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    terminal_status = "completed"
    try:
        task_result = await run_throughput_task(
            thread_id=thread_id,
            total_tokens=total_tokens,
            timeout_secs=_INGEST_TIMEOUT_SECS,
            node_execution_id=node_execution_id,
            t0_node=t0,
            node_id=node_id,
            task_id=task_id,
            stream_id=stream_id,
            # Override the task key so the UI shows "merge.ingest" not "mock_runner.throughput".
            task_name_override="MERGE",
        )
    except asyncio.CancelledError:
        terminal_status = "cancelled"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise
    except Exception:
        terminal_status = "failed"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise

    # run_throughput_task calls finish_node_execution internally; only emit node status.
    await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)

    return {
        "node_execution_id": node_execution_id,
        "task_id": task_result.pub_task_id,
        "result": task_result.result_str,
        "node_id": node_id,
        "task_id": task_id,
        "stream_id": stream_id,
    }


__all__ = ["merge_node"]
