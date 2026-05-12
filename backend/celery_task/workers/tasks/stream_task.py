"""Celery streaming worker — runs an LLM stream inside a Celery worker.

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
LLM → worker → ``fin:llm:tokens`` (Redis Stream, shard-routed) → Centrifugo
token-streaming tier → WebSocket channel ``thread:{thread_id}`` → UI.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

# ── Dynamic-batch tuning ─────────────────────────────────────────────────────
# Flush the token buffer when either limit is reached, whichever comes first.
# Larger batches → fewer Redis round-trips; smaller max-wait → lower latency.
_BATCH_MAX_SIZE: int = 16      # tokens per pipeline flush
_BATCH_FLUSH_MS: float = 8.0   # milliseconds between forced flushes

from backend.celery_task.celery_engine import celery_engine

logger = logging.getLogger(__name__)

def _extract_thinking_answer(text: str) -> tuple[str | None, str]:
    """Split a ``<think>…</think>`` prefix from the rest of the response.

    Args:
        text: Raw LLM output, possibly starting with a ``<think>`` block.

    Returns:
        A two-tuple ``(thinking, answer)`` where *thinking* is the content
        inside the ``<think>`` tag (or ``None`` when absent) and *answer* is
        the remaining text after ``</think>`` (or the full text when no
        ``<think>`` block is present).
    """
    stripped = text.strip()
    parts = stripped.split("<think>", 1)
    if len(parts) > 1:
        after_start = parts[1]
        thinking_parts = after_start.rsplit("</think>", 1)
        if len(thinking_parts) > 1:
            thinking = thinking_parts[0].strip() or None
            answer = thinking_parts[1].strip()
            return thinking, answer
    logger.error(
        "[stream_task] <think> block not found in LLM output; "
        "storing full response as answer. First 120 chars: %r",
        stripped[:120],
    )
    return None, text


async def _run_stream_async(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Async implementation of the streaming task.

    Args:
        thread_id:  LangGraph thread UUID (determines Centrifugo shard).
        task_id:    Governance UUID of the owning ``fin_agents.tasks`` row.
        task_name:  Human label, e.g. ``"stream_conclusion"``.
        node_name:  Owning node name, e.g. ``"conclusion_node"``.
        payload:    Dict containing at minimum ``"merged_research"`` context.

    Returns:
        ``{"answer": str, "total_tokens": int, "latency_ms": int}``
    """
    from backend.db.redis.streams.publisher import stream_token, stream_token_batch
    from backend.centrifugo_mq.client import has_app_viewers, has_thread_viewers
    from backend.centrifugo_mq.sse_notification.thread import notify as notify_thread
    from backend.centrifugo_mq.errors import STREAM_START_NACK
    from langchain_core.messages import HumanMessage

    query = payload.get("query", {})
    merged = payload.get("merged_research", {})
    context_text = merged.get("summary", "No research context available.")
    prompt = (
        f"Based on the following market research, provide a concise analysis "
        f"and conclusion for the user's query.\n\nResearch:\n{context_text}"
    )

    # Build the LLM based on settings.
    from backend.llm.factory import get_llm
    from backend.llm.providers import get_mock_llm
    from backend.llm.providers.mock_llm.word_pool import SEMANTIC_DURATION_SECS, SEMANTIC_TOKENS_PER_SEC

    provider = "mock"
    model_name = "mock"
    if query.startswith("semantic test") or query.startswith("concurrency test"):
        # Parse optional config encoded in the query by the frontend.
        # Format: "semantic test [tps=30 dur=10]: <detail>" — extras are ignored if absent.
        import re as _re
        _tps_m = _re.search(r"\btps=(\d+(?:\.\d+)?)", query)
        _dur_m = _re.search(r"\bdur=(\d+(?:\.\d+)?)", query)
        _tps = float(_tps_m.group(1)) if _tps_m else SEMANTIC_TOKENS_PER_SEC
        _dur = float(_dur_m.group(1)) if _dur_m else float(SEMANTIC_DURATION_SECS)
        llm = get_mock_llm(tokens_per_sec=_tps, duration_secs=_dur)
    else:
        llm = get_llm()

    # Check once whether any frontend client is watching this thread.
    # If the browser is closed (has_app_viewers=False), skip all centrifugo-llm
    # publishing — the full answer is still accumulated and persisted to DB.
    # If the app is open but on a different thread (has_thread_viewers=False),
    # also skip token streaming — the result will be visible via DB polling.
    viewers_present = (
        await has_app_viewers(thread_id)
        and await has_thread_viewers(thread_id)
    )

    # ── Pre-stream handshake: signal UI to connect to LLM MQ channel ─────────
    # Publish stream_start on the SSE tier and await ACK from the frontend.
    # The frontend defers its centrifugo-llm subscription until stream_start is
    # received, ensuring the MQ connection is ready before the first token
    # arrives.  When no app viewers are present, notify() returns True
    # immediately without publishing.
    acked = await notify_thread(
        thread_id,
        "stream_start",
        {"task_id": task_id, "task_name": task_name, "node_name": node_name},
        dedup_key=f"stream_start:{task_id}",
        retry_interval=5.0,
        max_retries=3,
    )
    if not acked:
        logger.error(
            "[%s] stream_start NACK thread_id=%s task_id=%s",
            STREAM_START_NACK, thread_id, task_id,
        )

    messages = [HumanMessage(content=prompt)]
    full_answer = ""
    total_tokens = 0
    seq = 0              # per-stream monotonic counter; starts at 1 on first token
    t0 = time.perf_counter()

    # ── Stream tokens → Centrifugo (dynamic-batch + seq) ─────────────
    # Tokens are accumulated into a batch and flushed whenever the batch
    # reaches _BATCH_MAX_SIZE or _BATCH_FLUSH_MS elapses, whichever comes
    # first.  Each token carries a monotonic `seq` so the frontend can
    # detect out-of-order or dropped messages and reassemble in order.
    # When no frontend client is watching, token publishing is skipped and
    # the output is cached locally for DB persistence only.
    batch: list[dict[str, Any]] = []
    batch_t0 = time.perf_counter()

    async for chunk in llm.astream(messages):
        token: str = chunk.content  # type: ignore[union-attr]
        if not token:
            continue
        full_answer += token
        total_tokens += 1
        seq += 1

        if viewers_present:
            batch.append(
                {
                    "event": "token",
                    "thread_id": thread_id,
                    "task_id": task_id,
                    "task_name": task_name,
                    "node_name": node_name,
                    "token": token,
                    "seq": seq,
                }
            )

            elapsed_ms = (time.perf_counter() - batch_t0) * 1_000
            if len(batch) >= _BATCH_MAX_SIZE or elapsed_ms >= _BATCH_FLUSH_MS:
                await stream_token_batch(thread_id, batch)
                batch.clear()
                batch_t0 = time.perf_counter()

    # Flush any remaining buffered tokens before signalling end-of-stream.
    if viewers_present and batch:
        await stream_token_batch(thread_id, batch)
        batch.clear()

    latency_ms = int((time.perf_counter() - t0) * 1000)

    # ── Extract thinking / answer from the full response ─────────────────
    # Post-process once: pull out a leading <think>…</think> block so it can
    # be stored separately in llm_responses.thinking and task output.
    thinking_text, answer_text = _extract_thinking_answer(full_answer)

    # ── Recover from Redis Stream, persist to PG, clean up Redis ─────
    # When viewers were present the tokens were published to the Redis Stream
    # and we recover prompt metadata from it before deleting the entries.
    # When no viewers were present there are no stream entries to recover.
    from backend.db.postgres.connection import raw_conn

    prompts_text: str | None = None
    entry_ids: list[Any] = []
    if viewers_present:
        from backend.db.redis.streams.reader import recover_task_tokens, delete_stream_entries
        text_by_column, entry_ids = await recover_task_tokens(thread_id, task_id)
        prompts_text = text_by_column.get("prompts")

    event_id = str(uuid.uuid4())

    async with raw_conn() as conn:
        await conn.execute(
            """
            INSERT INTO fin_agents.llm_responses
                (event_id, thread_id, task_id, provider, model,
                 task_name, node_name, prompts, thinking, answer,
                 output_tokens, total_tokens, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                thread_id,
                task_id,
                provider,
                model_name,
                task_name,
                node_name,
                prompts_text,
                thinking_text,
                answer_text,
                total_tokens,
                total_tokens,
                latency_ms,
            ),
        )

    if viewers_present:
        # Signal end-of-stream to the frontend.  `total_seq` mirrors `total_tokens`
        # and lets the UI confirm it has received every seq in [1 … total_seq].
        await stream_token(
            thread_id,
            {
                "event": "stream_end",
                "thread_id": thread_id,
                "task_id": task_id,
                "task_name": task_name,
                "node_name": node_name,
                "total_tokens": total_tokens,
                "total_seq": seq,
            },
        )
        if entry_ids:
            from backend.db.redis.streams.reader import delete_stream_entries
            await delete_stream_entries(thread_id, entry_ids)

    logger.info(
        "[stream_task] completed thread_id=%s task_name=%s tokens=%d latency_ms=%d viewers=%s",
        thread_id, task_name, total_tokens, latency_ms, viewers_present,
    )
    return {"thinking": thinking_text, "answer": answer_text, "total_tokens": total_tokens, "latency_ms": latency_ms}


# ---------------------------------------------------------------------------
# Celery task
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

    Tokens are published to ``fin:llm:tokens`` in real-time; the full response
    is persisted to ``fin_agents.llm_responses`` when streaming completes.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID for the ``fin_agents.tasks`` row.
        task_name:  Human label, e.g. ``"stream_conclusion"``.
        node_name:  Owning node name, e.g. ``"conclusion_node"``.
        payload:    Input context forwarded to the LLM.

    Returns:
        ``{"answer": str, "total_tokens": int, "latency_ms": int}``
    """
    return asyncio.run(
        _run_stream_async(thread_id, task_id, task_name, node_name, payload)
    )
