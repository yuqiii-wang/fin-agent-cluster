"""stream_runner — LangGraph leaf node for the streaming performance-test workflow.

Architecture
------------
This node is only activated when the user sends the trigger phrase
``"DO STREAMING PERFORMANCE TEST NOW"`` (case-insensitive, prefix match).
The outer graph routes all other queries to the ``fin_analyst_subgraph``.

Each invocation generates three runtime UUIDs written into state and emitted
via the ``started`` SSE event so the frontend can display the full execution
hierarchy:

* ``node_id``       — sub-graph node execution in the parent graph.
* ``leaf_node_id``  — this leaf-node execution inside the sub-graph.
* ``stream_id``     — the streaming session (Celery ingest run).

Token flow
----------
All token ingest runs inside the Celery ``stream:ingest`` worker
(:mod:`backend.streaming.workers.stream_ingest`).  FastAPI only dispatches the
Celery task and emits lifecycle events — it never touches token bytes.

Mode selection:
  Test parameters (test_mode, total_tokens, timeout_secs, token_per_sec) are
  encoded as JSON in the query string by the frontend::

      DO STREAMING PERFORMANCE TEST NOW|{"test_mode":"throughput",...} - label [uuid]

  :func:`_parse_perf_params` extracts them from ``state["query"]``.
  ``test_mode="throughput"``   → :func:`~tasks.throughput.run_throughput_task`
  ``test_mode="concurrency"``  → :func:`~tasks.concurrency.run_concurrency_task`
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import start_node_execution

logger = logging.getLogger(__name__)

_NODE_NAME: str = "stream_runner"

# ---------------------------------------------------------------------------
# Defaults — used when the frontend does not supply params in the query string.
# ---------------------------------------------------------------------------
_DEFAULT_TEST_MODE: str = "concurrency"
_DEFAULT_TOTAL_TOKENS: int = 100_000
_DEFAULT_TIMEOUT_SECS: int = 60
_DEFAULT_TOKEN_PER_SEC: int = 500


_RUN_ID_RE = re.compile(r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]\s*$", re.IGNORECASE)


def _parse_perf_params(query: str) -> tuple[str, int, int, int, str | None]:
    """Extract perf-test params and run_id from the query string.

    The frontend encodes params as JSON between the trigger phrase and the
    label suffix::

        DO STREAMING PERFORMANCE TEST NOW|{"test_mode":"throughput",
            "total_tokens":100000,"timeout_secs":60,"token_per_sec":500}
        - Stream #1 [run-uuid]

    The ``[run-uuid]`` suffix is shared across all streams in the same
    concurrency test run so the scheduler coordinator can group them.
    Falls back to defaults when no ``|`` separator is present.

    Args:
        query: Raw query string from ``StreamRunState``.

    Returns:
        Tuple ``(test_mode, total_tokens, timeout_secs, token_per_sec, run_id)``.
        ``run_id`` is ``None`` when the suffix is absent (legacy format).
    """
    # Extract run_id from the trailing [uuid] suffix — present regardless of
    # whether the JSON params block is included.
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
        logger.warning("[stream_runner] failed to parse perf params from query, using defaults")
        return _DEFAULT_TEST_MODE, _DEFAULT_TOTAL_TOKENS, _DEFAULT_TIMEOUT_SECS, _DEFAULT_TOKEN_PER_SEC, run_id


async def stream_runner(state: StreamRunState) -> dict:
    """Leaf node — route to throughput or concurrency task and emit lifecycle events.

    Generates ``node_id``, ``leaf_node_id``, and ``stream_id`` UUIDs then
    delegates to the mode-specific task, which owns the full Celery dispatch,
    SSE lifecycle, and node execution telemetry.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` populated by the runner.

    Returns:
        Partial state update containing ``node_id``, ``leaf_node_id``,
        ``stream_id``, ``task_id``, and ``result``.
    """
    from backend.graph.agents.streamer.tasks.throughput import run_throughput_task  # noqa: PLC0415
    from backend.graph.agents.streamer.tasks.concurrency import run_concurrency_task  # noqa: PLC0415

    thread_id: str = state["thread_id"]
    test_mode, total_tokens, timeout_secs, token_per_sec, run_id = _parse_perf_params(
        state.get("query", "")
    )

    logger.info(
        "[stream_runner] test_mode=%s total_tokens=%d timeout_secs=%d"
        " token_per_sec=%d run_id=%s thread_id=%s",
        test_mode, total_tokens, timeout_secs, token_per_sec, run_id, thread_id,
    )

    # Generate execution-identity UUIDs.
    node_id: str = str(uuid.uuid4())
    leaf_node_id: str = str(uuid.uuid4())
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
            "leaf_node_id": leaf_node_id,
            "stream_id": stream_id,
        },
        started_at,
    )

    if test_mode == "concurrency":
        task_result = await run_concurrency_task(
            thread_id=thread_id,
            token_per_sec=token_per_sec,
            timeout_secs=timeout_secs,
            node_execution_id=node_execution_id,
            t0_node=t0_node,
            node_id=node_id,
            leaf_node_id=leaf_node_id,
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
            leaf_node_id=leaf_node_id,
            stream_id=stream_id,
        )

    return {
        "task_id": task_result.pub_task_id,
        "result": task_result.result_str,
        "node_id": node_id,
        "leaf_node_id": leaf_node_id,
        "stream_id": stream_id,
    }
