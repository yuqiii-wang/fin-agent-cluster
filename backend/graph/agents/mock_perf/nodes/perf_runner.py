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
import uuid

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)

_DEFAULT_TEST_MODE: str = "concurrency"
_DEFAULT_TOTAL_TOKENS: int = 100_000
_DEFAULT_TIMEOUT_SECS: int = 60
_DEFAULT_TOKEN_PER_SEC: int = 100

_RUN_ID_RE = re.compile(
    r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]\s*$",
    re.IGNORECASE,
)


def _parse_perf_params(query: str) -> tuple[str, int, int, int, str | None]:
    """Extract perf-test params and optional run_id from the query string."""
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


class PerfRunnerNode(BaseNode):
    """Performance runner node implementation."""

    node_name: str = "mock_runner"

    def _create_node_output(self, task_result) -> dict:
        # Tasks handle finish_node_execution internally
        return {}

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_runner] completed thread_id=%s node_id=%s elapsed_ms=%d",
            thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(
        self,
        node_execution_id,
        node_id,
        task_id,
        task_result,
    ) -> dict:
        return {
            "node_execution_id": node_execution_id,
            "task_id": task_result.pub_task_id,
            "result": task_result.result_str,
            "node_id": node_id,
            "task_id": task_id,
            "stream_id": self._stream_id,
        }

    async def __call__(self, state: StreamRunState) -> dict:
        from backend.graph.agents.mock_perf.tasks.throughput import run_throughput_task
        from backend.graph.agents.mock_perf.tasks.concurrency import run_concurrency_task

        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        test_mode, total_tokens, timeout_secs, token_per_sec, run_id = _parse_perf_params(
            state.get("query", "")
        )

        logger.info(
            "[mock_runner] test_mode=%s total_tokens=%d timeout_secs=%d"
            " token_per_sec=%d run_id=%s thread_id=%s",
            test_mode, total_tokens, timeout_secs, token_per_sec, run_id, thread_id,
        )

        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())
        self._stream_id: str = str(uuid.uuid4())

        node_input = {
            "total_tokens": total_tokens,
            "timeout_secs": timeout_secs,
            "test_mode": test_mode,
            "token_per_sec": token_per_sec,
            "node_id": node_id,
            "task_id": task_id,
            "stream_id": self._stream_id,
        }

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            if test_mode == "concurrency":
                return await run_concurrency_task(
                    thread_id=thread_id_arg,
                    token_per_sec=token_per_sec,
                    timeout_secs=timeout_secs,
                    node_execution_id=node_execution_id_arg,
                    node_id=node_id_arg,
                    task_id=task_id,
                    stream_id=self._stream_id,
                    run_id=run_id,
                    t0_node=None,
                )
            else:
                return await run_throughput_task(
                    thread_id=thread_id_arg,
                    total_tokens=total_tokens,
                    timeout_secs=timeout_secs,
                    node_execution_id=node_execution_id_arg,
                    node_id=node_id_arg,
                    task_id=task_id,
                    stream_id=self._stream_id,
                    t0_node=None,
                )

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            use_start_finish=True,
        )


_perf_runner_instance = PerfRunnerNode()


async def perf_runner(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for PerfRunnerNode class."""
    return await _perf_runner_instance(state)


__all__ = ["perf_runner"]
