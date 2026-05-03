"""perf_runner — LangGraph node for the mock streaming performance-test workflow.

Handles the ``"DO STREAMING PERFORMANCE TEST NOW"`` trigger phrase.
Routes to throughput or concurrency ingest via the existing task functions.

Emits node_status SSE events at 'running' and terminal states so the UI
can track per-node lifecycle independently.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import start_node_execution, update_node_execution_status
from backend.sse_notifications.node import emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_runner"

_DEFAULT_TEST_MODE: str = "concurrency"
_DEFAULT_TOTAL_TOKENS: int = 100_000
_DEFAULT_TIMEOUT_SECS: int = 60
_DEFAULT_TOKEN_PER_SEC: int = 100

_RUN_ID_RE = re.compile(
    r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]\s*$",
    re.IGNORECASE,
)


def _parse_perf_params(query: str) -> tuple[str, int, int, int, str | None]:
    """Extract perf-test params and optional run_id from the query string.

    Args:
        query: Raw query string from ``StreamRunState``.

    Returns:
        Tuple ``(test_mode, total_tokens, timeout_secs, token_per_sec, run_id)``.
    """
    run_id_match = _RUN_ID_RE.search(query)
    run_id: str | None = run_id_match.group(1) if run_id_match else None

    if "|" not in query:
        return _DEFAULT_TEST_MODE, _DEFAULT_TOTAL_TOKENS, _DEFAULT_TIMEOUT_SECS, _DEFAULT_TOKEN_PER_SEC, run_id
    try:
        pipe_idx = query.index("|")
        rest = query[pipe_idx + 1:]
        json_str = rest.split(" - ")[0].strip()
        params: dict = json.loads(json_str)
        return (
            str(params.get("test_mode", _DEFAULT_TEST_MODE)),
            int(params.get("total_tokens", _DEFAULT_TOTAL_TOKENS)),
            int(params.get("timeout_secs", _DEFAULT_TIMEOUT_SECS)),
            int(params.get("token_per_sec", _DEFAULT_TOKEN_PER_SEC)),
            run_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("[perf_runner] failed to parse perf params, using defaults")
        return _DEFAULT_TEST_MODE, _DEFAULT_TOTAL_TOKENS, _DEFAULT_TIMEOUT_SECS, _DEFAULT_TOKEN_PER_SEC, run_id


async def perf_runner(state: StreamRunState) -> dict:
    """Node — route to throughput or concurrency task and emit lifecycle events.

    Generates ``node_id``, ``task_id``, and ``stream_id`` UUIDs then
    delegates to the mode-specific task, which owns the full Celery dispatch,
    SSE lifecycle, and node execution telemetry.

    Emits ``node_status`` SSE events at 'running' (start) and the terminal
    status so the frontend can track node-level lifecycle independently of
    task-level events.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` populated by the runner.

    Returns:
        Partial state update containing ``node_id``, ``task_id``,
        ``stream_id``, ``task_id``, and ``result``.
    """
    from backend.graph.agents.mock_perf.tasks.throughput import run_throughput_task  # noqa: PLC0415
    from backend.graph.agents.mock_perf.tasks.concurrency import run_concurrency_task  # noqa: PLC0415

    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    test_mode, total_tokens, timeout_secs, token_per_sec, run_id = _parse_perf_params(
        state.get("query", "")
    )

    logger.info(
        "[perf_runner] test_mode=%s total_tokens=%d timeout_secs=%d"
        " token_per_sec=%d run_id=%s thread_id=%s",
        test_mode, total_tokens, timeout_secs, token_per_sec, run_id, thread_id,
    )

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    stream_id: str = str(uuid.uuid4())
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
        if test_mode == "concurrency":
            task_result = await run_concurrency_task(
                thread_id=thread_id,
                token_per_sec=token_per_sec,
                timeout_secs=timeout_secs,
                node_execution_id=node_execution_id,
                t0_node=t0_node,
                node_id=node_id,
                task_id=task_id,
                stream_id=stream_id,
                run_id=run_id,
            )
        else:
            task_result = await run_throughput_task(
                thread_id=thread_id,
                total_tokens=total_tokens,
                timeout_secs=timeout_secs,
                node_execution_id=node_execution_id,
                t0_node=t0_node,
                node_id=node_id,
                task_id=task_id,
                stream_id=stream_id,
            )
    except Exception:
        terminal_status = "failed"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise

    # run_throughput_task / run_concurrency_task already call finish_node_execution
    # internally, so we only need to update the node status here.
    await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)

    return {
        "node_execution_id": node_execution_id,
        "task_id": task_result.pub_task_id,
        "result": task_result.result_str,
        "node_id": node_id,
        "task_id": task_id,
        "stream_id": stream_id,
    }


__all__ = ["perf_runner"]
