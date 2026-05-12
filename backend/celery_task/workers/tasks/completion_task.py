"""Celery completion worker — unified dispatcher for non-streaming handlers.

The LangGraph ``@task`` dispatches work here via
``celery_engine.send_task("backend.celery_task.workers.tasks.completion_task.run_completion", ...)``.
The LangGraph thread polls / blocks on the AsyncResult until the worker
returns, then resumes the graph with the result.

Handlers live in ``backend.langgraph.nodes`` (assembled from each node's
``tasks`` sub-package).  To add a new handler, create a task module under
``backend/langgraph/nodes/<node_name>/tasks/`` and add the ``NodeTask``
instance to the node's ``tasks/__init__.py`` HANDLERS slice — no changes
are needed here.

Task signature
--------------
Arguments (positional, serialised as JSON by Celery):
    task_name  (str)  — key into ``backend.langgraph.tasks.HANDLERS``.
    payload    (dict) — arbitrary input forwarded to the handler.

Return value (stored in Redis backend):
    dict — the result produced by the handler, ready to be merged into
    :class:`~backend.langgraph.state.GraphState`.

DB write
--------
``persist_task_result`` is called for durability: the task row reflects the
terminal state even if the graph runner is interrupted.  SSE is NOT emitted
here — it is the graph runner's responsibility after ``delegate_completion``
returns.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.celery_task.celery_engine import celery_engine
from backend.langgraph.nodes import HANDLERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_engine.task(name="backend.celery_task.workers.tasks.completion_task.run_completion")
def run_completion(
    thread_id: str,
    task_id: str,
    node_id: str,
    node_name: str,
    task_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute a non-streaming handler synchronously inside a Celery worker.

    Persists the outcome (success or failure) to ``fin_agents.tasks`` before
    returning, so the database row reflects the terminal state even if the
    LangGraph caller is interrupted.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID of the owning ``fin_agents.tasks`` row.
        node_id:    Owning node's ID.
        node_name:  Owning node's human-readable name.
        task_name:  Key into ``HANDLERS`` (e.g. ``"analyze_query"``).
        payload:    Dict forwarded verbatim to the handler.

    Returns:
        Handler result dict, stored in the Celery result backend (Redis).

    Raises:
        ValueError: When *task_name* is unknown.
        Exception:  Any exception raised by the handler is re-raised so
                    Celery marks the task FAILURE and the LangGraph ``@task``
                    propagates it to the caller.
    """
    handler = HANDLERS.get(task_name)
    if handler is None:
        raise ValueError(f"Unknown completion task: {task_name!r}")

    # Log queue wait time: time between task creation (in DB) and worker pickup.
    # Uses wall clock; compare with dispatch_ms from delegate_completion in graph.log.
    _t_start = time.monotonic()
    logger.info(
        "[completion_task] start task_id=%s task_name=%s thread_id=%s",
        task_id, task_name, thread_id,
    )

    async def _run() -> dict[str, Any]:
        from backend.langgraph.lifecycle import persist_task_result

        try:
            result = await handler(payload)
        except Exception as exc:
            await persist_task_result(
                thread_id, node_id, node_name, task_id, task_name,
                failed=True, error=str(exc),
            )
            raise
        await persist_task_result(
            thread_id, node_id, node_name, task_id, task_name,
            output_data=result,
        )
        return result

    result = asyncio.run(_run())
    logger.debug(
        "[completion_task] done task_id=%s task_name=%s handler_ms=%.0f",
        task_id, task_name, (time.monotonic() - _t_start) * 1000,
    )
    return result
