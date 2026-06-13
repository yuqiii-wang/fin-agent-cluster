"""Celery streaming worker -- runs an LLM stream inside a Celery worker.

Flow
----
1. LangGraph ``@task`` dispatches ``run_stream`` with a ``thread_id`` and
   ``payload``.
2. The worker streams tokens from the LLM.
3. Each token is published to ``fin:llm:tokens`` (via
   :func:`~backend.db.redis.streams.publisher.stream_token`) so Centrifugo
   forwards it to the subscribed WebSocket/SSE client in real-time.
4. After the stream ends the full response is persisted to
   ``fin_agents.llm_responses``.
5. The task returns a summary dict; Celery stores it in the result backend so
   the LangGraph thread can retrieve it and mark the task completed.

Token delivery path
-------------------
LLM -> worker -> ``fin:llm:tokens`` (Redis Stream, shard-routed) -> Centrifugo
token-streaming tier -> WebSocket channel ``thread:{thread_id}`` -> UI.

Implementation is split across ``stream_utils/``:
  text_utils       -- extract_thinking_answer, extract_json_from_text
  llm_selection    -- select_llm
  prompt_registry  -- STREAM_PROMPT_BUILDERS, get_stream_prompt_builders
  stream_core      -- run_stream_core (main streaming loop)
  prompt_builder   -- run_stream_async (stream_llm / conclusion-node path)
  compact_continue -- detect_and_compress_repetition, run_stream_compact_continue_async
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.celery_task.celery_engine import celery_engine
from backend.celery_task.workers.tasks.stream_utils import (
    detect_and_compress_repetition,
    get_stream_prompt_builders,
    run_stream_async,
    run_stream_compact_continue_async,
    run_stream_core,
    select_llm,
)


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery_engine.task(name="backend.celery_task.workers.tasks.stream_task.run_stream")
def run_stream(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute the streaming LLM handler inside a Celery worker.

    Dispatches to a registered prompt builder when *task_name* is found in
    ``STREAM_PROMPT_BUILDERS``; falls back to the ``stream_llm`` path
    otherwise (builds its own prompt from the payload).  LLM selection
    (mock vs Ollama) is delegated to ``select_llm`` which inspects the
    query for test-mode prefixes.

    Tokens are published to ``fin:llm:tokens`` in real-time; the full response
    is persisted to ``fin_agents.llm_responses`` when streaming completes.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID for the ``fin_agents.tasks`` row.
        task_name:  Human label, e.g. ``"stream_llm"``, ``"analyze_query"``.
        node_name:  Owning node name.
        payload:    Input context forwarded to the LLM.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
    """
    from backend.langgraph.agent.error_log import bind_log_thread_id

    bind_log_thread_id(thread_id)
    builders = get_stream_prompt_builders()
    if task_name in builders:
        messages = builders[task_name](payload)
        llm = select_llm(payload.get("query", ""))
        return asyncio.run(
            run_stream_core(thread_id, task_id, task_name, node_name, payload, messages, llm)
        )
    return asyncio.run(
        run_stream_async(thread_id, task_id, task_name, node_name, payload)
    )


@celery_engine.task(
    name="backend.celery_task.workers.tasks.stream_task.run_stream_compact_continue"
)
def run_stream_compact_continue(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
    prior_thinking_full: str,
    prior_thinking_compressed: str,
) -> dict[str, Any]:
    """Execute a compact-and-continue streaming retry inside a Celery worker.

    Continues from a prior streaming run that was interrupted by token repetition.
    The compressed prior thinking is injected as context so the LLM can reason
    forward without looping.  The final stored thinking is the concatenation of
    *prior_thinking_full* and the new thinking produced in this run.

    Args:
        thread_id:               LangGraph thread UUID.
        task_id:                 Governance UUID for the ``fin_agents.tasks`` row.
        task_name:               UI-facing task label.
        node_name:               Owning node name.
        payload:                 Original serialised task input.
        prior_thinking_full:     Complete prior thinking text (uncompressed).
        prior_thinking_compressed: Prior thinking with repeating blocks compressed.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
    """
    from backend.langgraph.agent.error_log import bind_log_thread_id

    bind_log_thread_id(thread_id)
    return asyncio.run(
        run_stream_compact_continue_async(
            thread_id, task_id, task_name, node_name, payload,
            prior_thinking_full, prior_thinking_compressed,
        )
    )

