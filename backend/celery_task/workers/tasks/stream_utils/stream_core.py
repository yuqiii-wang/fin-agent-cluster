"""Provider-agnostic streaming loop for LLM Celery tasks."""

from __future__ import annotations

import time
import uuid
import logging
from typing import Any

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# ── Dynamic-batch tuning ─────────────────────────────────────────────────────
# Flush the token buffer when either limit is reached, whichever comes first.
# Larger batches -> fewer Redis round-trips; smaller max-wait -> lower latency.
BATCH_MAX_SIZE: int = 16      # tokens per pipeline flush
BATCH_FLUSH_MS: float = 8.0   # milliseconds between forced flushes


async def run_stream_core(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
    messages: list[BaseMessage],
    llm: Any,
) -> dict[str, Any]:
    """Provider-agnostic streaming loop.

    Streams tokens from *llm*, publishes batches to Centrifugo, persists
    the full response to ``fin_agents.llm_responses``.  Provider and model
    metadata are read directly from ``llm.provider`` and ``llm.model`` so
    this function does not hardcode any provider details.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID of the ``fin_agents.tasks`` row.
        task_name:  Task label for SSE events and DB rows.
        node_name:  Owning node name.
        payload:    Original serialised task input (stored in DB for reference).
        messages:   LangChain message list (SystemMessage + HumanMessage).
        llm:        Any ``BaseChatModel`` instance with ``.provider`` and
                    ``.model`` attributes.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
    """
    import json
    from backend.db.redis.streams.publisher import stream_token, stream_token_batch
    from backend.centrifugo_mq.client import has_app_viewers, has_thread_viewers
    from backend.centrifugo_mq.sse_notification.thread import notify as notify_thread
    from backend.centrifugo_mq.errors import STREAM_START_NACK
    from backend.db.postgres.connection import raw_conn
    from .text_utils import extract_thinking_answer, extract_json_from_text

    provider: str = getattr(llm, "provider", "unknown")
    model_name: str = getattr(llm, "model", "unknown")

    # Send stream_start BEFORE checking viewers_present.
    # The Celery worker may pick up this task before the frontend has had time
    # to process the preceding task_status:running SSE and subscribe to the
    # Centrifugo token channel.  stream_start gives the frontend that window:
    # the ACK means the frontend has received and handled the event (and is now
    # subscribed).  Checking viewers_present before stream_start races against
    # that subscription and produces False negatives -> no tokens sent.
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

    # Re-check after stream_start: if the event was acked the frontend is now
    # subscribed; if not acked (timeout/nack) still re-check in case the
    # subscriber arrived during the retry window.
    viewers_present = (
        await has_app_viewers(thread_id)
        and await has_thread_viewers(thread_id)
    )
    full_answer = ""
    total_tokens = 0
    seq = 0
    t0 = time.perf_counter()
    batch: list[dict[str, Any]] = []
    batch_t0 = time.perf_counter()
    # Tracks whether a provider-level thinking block is currently open.
    # Used only when a provider exposes raw thinking tokens in
    # ``chunk.additional_kwargs["thinking"]`` (e.g. Anthropic extended thinking)
    # rather than normalising them into ``chunk.content`` as ``<think>...</think>``
    # (Ollama's approach).  Both paths produce the same ``full_answer`` shape so
    # ``extract_thinking_answer`` works identically regardless of provider.
    _provider_thinking_open = False

    async for chunk in llm.astream(messages):
        # Anthropic-style: raw thinking in additional_kwargs["thinking"],
        # content empty during reasoning phase.
        raw_thinking: str = (
            (getattr(chunk, "additional_kwargs", None) or {}).get("thinking", "") or ""
        )
        raw_content: str = chunk.content or ""  # type: ignore[union-attr]

        if raw_thinking:
            # Wrap raw thinking in <think>...</think> so extract_thinking_answer
            # works uniformly across all providers.
            if not _provider_thinking_open:
                _provider_thinking_open = True
                token = "<think>" + raw_thinking
            else:
                token = raw_thinking
        elif raw_content:
            if _provider_thinking_open:
                # First content token after raw thinking -- close the tag.
                _provider_thinking_open = False
                token = "</think>" + raw_content
            else:
                # Normal content token (Ollama already has <think> inline).
                token = raw_content
        else:
            continue

        full_answer += token
        total_tokens += 1
        seq += 1

        # Cancel check every 20 tokens so the Ollama HTTP stream is closed
        # promptly when the thread is cancelled, freeing GPU resources without
        # a per-token Redis round-trip.
        if seq % 20 == 0:
            from backend.langgraph.lifecycle.cancel_flag import is_cancel_flag_set as _is_cancelled
            if await _is_cancelled(thread_id):
                logger.error(
                    "[stream_task] cancel_mid_stream thread_id=%s task_id=%s tokens=%d",
                    thread_id, task_id, seq,
                )
                # Break closes the async generator -> httpx connection -> Ollama stops.
                break
            from backend.langgraph.lifecycle.pause_flag import is_task_pause_flag_set
            if await is_task_pause_flag_set(task_id):
                logger.debug(
                    "[stream_task] pause_mid_stream task_id=%s tokens=%d",
                    task_id, seq,
                )
                break

        if viewers_present:
            batch.append({
                "event": "token",
                "thread_id": thread_id,
                "task_id": task_id,
                "task_name": task_name,
                "node_name": node_name,
                "token": token,
                "seq": seq,
            })
            elapsed_ms = (time.perf_counter() - batch_t0) * 1_000
            if len(batch) >= BATCH_MAX_SIZE or elapsed_ms >= BATCH_FLUSH_MS:
                await stream_token_batch(thread_id, batch)
                batch.clear()
                batch_t0 = time.perf_counter()

    # Defensive: close an unclosed provider thinking block (should not occur).
    if _provider_thinking_open:
        full_answer += "</think>"

    if viewers_present and batch:
        await stream_token_batch(thread_id, batch)
        batch.clear()

    # If the streaming loop was interrupted by a pause flag, return a paused result
    # (SUCCESS with paused=True) so the caller can save the partial thinking snapshot.
    from backend.langgraph.lifecycle.pause_flag import is_task_pause_flag_set
    if await is_task_pause_flag_set(task_id):
        # Close any unclosed reasoning tag caused by the mid-stream pause so
        # extract_thinking_answer does not fire a spurious error.
        for _ot, _ct in (("<think>", "</think>"), ("<thinking>", "</thinking>")):
            if _ot in full_answer and _ct not in full_answer:
                full_answer += _ct
        thinking_text, _ = extract_thinking_answer(full_answer)
        return {
            "paused": True,
            "thinking": thinking_text,
            "answer": {},
            "total_tokens": total_tokens,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    # If the streaming loop was interrupted by the cancel flag, raise now so
    # the Celery task is stored as failed, freeing the LangGraph error path.
    from backend.langgraph.lifecycle.cancel_flag import is_cancel_flag_set as _is_cancelled
    if await _is_cancelled(thread_id):
        raise RuntimeError(f"[stream_task] stream cancelled thread_id={thread_id} task_id={task_id}")

    latency_ms = int((time.perf_counter() - t0) * 1000)
    thinking_text, answer_text = extract_thinking_answer(full_answer)

    # Serialize the messages list (SystemMessage + HumanMessage) into a
    # human-readable prompt text for DB storage.  This is always available
    # regardless of whether viewers are present.
    _type_labels = {
        "system": "SYSTEM",
        "human": "HUMAN",
        "ai": "AI",
    }
    prompts_text: str | None = "\n\n".join(
        f"{_type_labels.get(m.type, m.type.upper())}:\n{m.content}"
        for m in messages
        if getattr(m, "content", None)
    ) or None

    entry_ids: list[Any] = []
    if viewers_present:
        from backend.db.redis.streams.reader import recover_task_tokens, delete_stream_entries
        _text_by_column, entry_ids = await recover_task_tokens(thread_id, task_id)

    import hashlib
    prompt_hash: str | None = (
        hashlib.md5(prompts_text.encode()).hexdigest() if prompts_text else None
    )

    event_id = str(uuid.uuid4())
    async with raw_conn() as conn:
        await conn.execute(
            """
            INSERT INTO fin_agents.llm_responses
                (event_id, thread_id, task_id, provider, model,
                 task_name, node_name, prompts, prompt_hash, thinking, answer,
                 output_tokens, total_tokens, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id, thread_id, task_id, provider, model_name,
                task_name, node_name, prompts_text, prompt_hash, thinking_text, answer_text,
                total_tokens, total_tokens, latency_ms,
            ),
        )

    if viewers_present:
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

    try:
        answer_dict: dict[str, Any] = json.loads(answer_text)
    except (json.JSONDecodeError, TypeError):
        answer_dict = extract_json_from_text(answer_text)

    return {"thinking": thinking_text, "answer": answer_dict, "total_tokens": total_tokens, "latency_ms": latency_ms}
