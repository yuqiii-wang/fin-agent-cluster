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
import json
import logging
import time
import uuid
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

# ── Dynamic-batch tuning ─────────────────────────────────────────────────────
# Flush the token buffer when either limit is reached, whichever comes first.
# Larger batches → fewer Redis round-trips; smaller max-wait → lower latency.
_BATCH_MAX_SIZE: int = 16      # tokens per pipeline flush
_BATCH_FLUSH_MS: float = 8.0   # milliseconds between forced flushes

from backend.celery_task.celery_engine import celery_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream prompt builder registry
# ---------------------------------------------------------------------------
# Maps task_name → callable(payload: dict) -> str.
# Tasks that run via delegate_stream register their prompt builders here.
# Populated lazily on first use to avoid circular imports at module load time.
_STREAM_PROMPT_BUILDERS: dict[str, Any] = {}


def _get_stream_prompt_builders() -> dict[str, Any]:
    """Lazily load and merge all registered stream prompt builders."""
    if _STREAM_PROMPT_BUILDERS:
        return _STREAM_PROMPT_BUILDERS
    from backend.langgraph.nodes.query_node.tasks import STREAM_PROMPT_BUILDERS as _QPB
    from backend.langgraph.nodes.prepare_peers.tasks import STREAM_PROMPT_BUILDERS as _APB
    _STREAM_PROMPT_BUILDERS.update(_QPB)
    _STREAM_PROMPT_BUILDERS.update(_APB)
    return _STREAM_PROMPT_BUILDERS


def _select_llm(query: str) -> Any:
    """Select LLM based on query prefix.

    Returns a ``MockLLM`` (with optional rate/duration overrides) when the
    query starts with ``"semantic test"`` or ``"concurrency test"``, so
    load-testing flows never reach the real Ollama endpoint.  All other
    queries use ``OllamaLLM``.

    Args:
        query: Raw user query string from the task payload.

    Returns:
        A ``BaseChatModel`` instance whose ``.provider`` and ``.model``
        attributes carry metadata for DB storage.
    """
    import re
    from backend.llm.factory import get_llm
    from backend.llm.providers.mock_llm import get_mock_llm
    from backend.llm.providers.mock_llm.word_pool import SEMANTIC_DURATION_SECS, SEMANTIC_TOKENS_PER_SEC

    if query.startswith("semantic test") or query.startswith("concurrency test"):
        _tps_m = re.search(r"\btps=(\d+(?:\.\d+)?)", query)
        _dur_m = re.search(r"\bdur=(\d+(?:\.\d+)?)", query)
        _tps = float(_tps_m.group(1)) if _tps_m else SEMANTIC_TOKENS_PER_SEC
        _dur = float(_dur_m.group(1)) if _dur_m else float(SEMANTIC_DURATION_SECS)
        return get_mock_llm(tokens_per_sec=_tps, duration_secs=_dur)
    return get_llm("ollama")

def _extract_thinking_answer(text: str) -> tuple[str | None, str]:
    """Split a reasoning block from the rest of the streamed response.

    Handles two tag variants produced by different LLM providers:

    * ``<think>…</think>`` — Ollama reasoning models (e.g. Qwen3) after
      normalisation by :meth:`OllamaLLM._astream`.
    * ``<thinking>…</thinking>`` — Anthropic-style extended thinking or
      models that emit the tag verbatim.

    If the close tag is missing (stream was truncated), the remaining text
    is treated as thinking and the answer is returned as an empty string so
    callers can detect the incomplete state.

    If no reasoning block is present (normal for non-reasoning models and
    MockLLM) the full text is returned as the answer with ``thinking=None``.

    Args:
        text: Raw accumulated LLM output.

    Returns:
        A two-tuple ``(thinking, answer)`` where *thinking* is the content
        inside the reasoning tag (or ``None`` when absent) and *answer* is
        the remaining text after the close tag.
    """
    stripped = text.strip()
    for open_tag, close_tag in (("<think>", "</think>"), ("<thinking>", "</thinking>")):
        if open_tag not in stripped:
            continue
        before, _, after_open = stripped.partition(open_tag)
        if close_tag in after_open:
            thinking_raw, _, answer = after_open.partition(close_tag)
            return thinking_raw.strip() or None, answer.strip()
        # Close tag missing — stream was truncated or model forgot to close it.
        logger.error(
            "[stream_task] %s opened but %s never closed in LLM output; "
            "treating remaining text as thinking. First 120: %r",
            open_tag, close_tag, after_open[:120],
        )
        return after_open.strip() or None, ""
    # No reasoning block — normal for non-reasoning models (MockLLM, plain Ollama).
    return None, stripped


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract a JSON object from text that may contain markdown fences or prose.

    Handles LLM responses that wrap the JSON in ````json … ```` fences or
    prefix it with explanation text.  Falls back to ``{"raw": text}`` when no
    parseable JSON object is found, which allows callers to inspect the raw
    output for debugging.

    Args:
        text: Raw answer text after thinking has been stripped.

    Returns:
        Parsed JSON dict, or ``{"raw": text}`` on failure.
    """
    stripped = text.strip()

    # Strip common markdown code fences (```json … ``` or ``` … ```)
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip() == "```":
            inner_lines = inner_lines[:-1]
        stripped = "\n".join(inner_lines).strip()

    # Try direct parse first (fast path)
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Find the first balanced { … } block in the text
    start = stripped.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(stripped[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break

    logger.error(
        "[stream_task] JSON extraction failed; storing raw text. First 120: %r",
        stripped[:120],
    )
    return {"raw": text}


async def _run_stream_core(
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
    from backend.db.redis.streams.publisher import stream_token, stream_token_batch
    from backend.centrifugo_mq.client import has_app_viewers, has_thread_viewers
    from backend.centrifugo_mq.sse_notification.thread import notify as notify_thread
    from backend.centrifugo_mq.errors import STREAM_START_NACK
    from backend.db.postgres.connection import raw_conn

    provider: str = getattr(llm, "provider", "unknown")
    model_name: str = getattr(llm, "model", "unknown")

    # Send stream_start BEFORE checking viewers_present.
    # The Celery worker may pick up this task before the frontend has had time
    # to process the preceding task_status:running SSE and subscribe to the
    # Centrifugo token channel.  stream_start gives the frontend that window:
    # the ACK means the frontend has received and handled the event (and is now
    # subscribed).  Checking viewers_present before stream_start races against
    # that subscription and produces False negatives → no tokens sent.
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
    # rather than normalising them into ``chunk.content`` as ``<think>…</think>``
    # (Ollama's approach).  Both paths produce the same ``full_answer`` shape so
    # ``_extract_thinking_answer`` works identically regardless of provider.
    _provider_thinking_open = False

    async for chunk in llm.astream(messages):
        # Anthropic-style: raw thinking in additional_kwargs["thinking"],
        # content empty during reasoning phase.
        raw_thinking: str = (
            (getattr(chunk, "additional_kwargs", None) or {}).get("thinking", "") or ""
        )
        raw_content: str = chunk.content or ""  # type: ignore[union-attr]

        if raw_thinking:
            # Wrap raw thinking in <think>…</think> so _extract_thinking_answer
            # works uniformly across all providers.
            if not _provider_thinking_open:
                _provider_thinking_open = True
                token = "<think>" + raw_thinking
            else:
                token = raw_thinking
        elif raw_content:
            if _provider_thinking_open:
                # First content token after raw thinking — close the tag.
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
                # Break closes the async generator → httpx connection → Ollama stops.
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
            if len(batch) >= _BATCH_MAX_SIZE or elapsed_ms >= _BATCH_FLUSH_MS:
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
        # _extract_thinking_answer does not fire a spurious error.
        for _ot, _ct in (("<think>", "</think>"), ("<thinking>", "</thinking>")):
            if _ot in full_answer and _ct not in full_answer:
                full_answer += _ct
        thinking_text, _ = _extract_thinking_answer(full_answer)
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
    thinking_text, answer_text = _extract_thinking_answer(full_answer)

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
                event_id, thread_id, task_id, provider, model_name,
                task_name, node_name, prompts_text, thinking_text, answer_text,
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
        answer_dict = _extract_json_from_text(answer_text)

    return {"thinking": thinking_text, "answer": answer_dict, "total_tokens": total_tokens, "latency_ms": latency_ms}


async def _run_stream_async(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the stream_llm prompt and delegate to ``_run_stream_core``.

    Handles the ``stream_llm`` path which builds its own prompt from the
    merged research payload rather than using a registered builder.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID of the owning ``fin_agents.tasks`` row.
        task_name:  Human label, e.g. ``"stream_llm"``.
        node_name:  Owning node name, e.g. ``"conclusion_node"``.
        payload:    Serialised ``ConclusionNodeInput`` dict.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
        where ``answer`` has keys: summary, recommendation, confidence, key_points, risk_factors.
    """
    query = payload.get("query", "")
    stats_analysis = payload.get("stats_analysis", "")
    stats_key_metrics = payload.get("stats_key_metrics", {})
    news_sentiment = payload.get("news_sentiment", "")
    news_highlights: list[str] = payload.get("news_highlights", [])

    highlights_text = "\n".join(f"- {h}" for h in news_highlights) if news_highlights else "No highlights."
    metrics_text = json.dumps(stats_key_metrics, indent=2) if stats_key_metrics else "N/A"

    system_content = (
        "You are a quantitative financial analyst. Produce structured investment conclusions "
        "based on market research. Respond ONLY with a JSON object (no markdown fences, no extra "
        "text) with exactly these fields:\n"
        '{"summary": "<2-3 sentence overall conclusion>", '
        '"recommendation": "<Buy|Sell|Hold>", '
        '"confidence": "<High|Medium|Low>", '
        '"key_points": ["<point1>", "<point2>", ...], '
        '"risk_factors": ["<risk1>", "<risk2>", ...]}'
    )
    human_content = (
        f"Query: {query}\n\n"
        f"Statistical Analysis:\n{stats_analysis or 'Not available.'}\n\n"
        f"Key Metrics:\n{metrics_text}\n\n"
        f"News Sentiment:\n{news_sentiment or 'Not available.'}\n\n"
        f"News Highlights:\n{highlights_text}"
    )
    messages = [SystemMessage(content=system_content), HumanMessage(content=human_content)]

    llm = _select_llm(query)
    return await _run_stream_core(thread_id, task_id, task_name, node_name, payload, messages, llm)


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

    Dispatches to a registered prompt builder when *task_name* is found in
    ``STREAM_PROMPT_BUILDERS``; falls back to the ``stream_llm`` path
    otherwise (builds its own prompt from the payload).  LLM selection
    (mock vs Ollama) is delegated to ``_select_llm`` which inspects the
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
    builders = _get_stream_prompt_builders()
    if task_name in builders:
        messages = builders[task_name](payload)
        llm = _select_llm(payload.get("query", ""))
        return asyncio.run(
            _run_stream_core(thread_id, task_id, task_name, node_name, payload, messages, llm)
        )
    return asyncio.run(
        _run_stream_async(thread_id, task_id, task_name, node_name, payload)
    )


# ---------------------------------------------------------------------------
# Compact-and-continue helpers
# ---------------------------------------------------------------------------


def _detect_and_compress_repetition(thinking: str) -> tuple[str, str, int]:
    """Detect consecutive line repetition at the end of *thinking* and compress it.

    Splits *thinking* by newline and searches for the largest suffix where a
    fixed-length block of lines repeats at least twice consecutively.  Returns
    the non-repeating prefix, the repeating block text, and the repetition count.

    If no repetition is found ``repeat_count`` is 0 and ``repeating_block`` is
    an empty string.

    Args:
        thinking: Raw thinking text from a prior LLM streaming run.

    Returns:
        Tuple ``(non_repeating_prefix, repeating_block, repeat_count)`` where
        ``repeat_count >= 2`` means repetition was detected.
    """
    lines = thinking.split("\n")
    n = len(lines)
    if n < 2:
        return thinking, "", 0

    best_count = 1
    best_block_size = 0
    best_start = n

    # Try every block size from 1 up to half the total lines.
    for block_size in range(1, n // 2 + 1):
        block = lines[n - block_size:]
        count = 1
        pos = n - block_size
        while pos >= block_size and lines[pos - block_size:pos] == block:
            count += 1
            pos -= block_size
        if count >= 2 and count > best_count:
            best_count = count
            best_block_size = block_size
            best_start = pos

    if best_count < 2:
        return thinking, "", 0

    non_repeating = "\n".join(lines[:best_start])
    repeating_block = "\n".join(lines[best_start:best_start + best_block_size])
    return non_repeating, repeating_block, best_count


async def _run_stream_compact_continue_async(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
    prior_thinking_full: str,
    prior_thinking_compressed: str,
) -> dict[str, Any]:
    """Run a compact-and-continue retry stream.

    Builds the original prompt from *payload*, appends the compressed prior
    thinking as context, streams from the LLM, then stores the concatenation
    of *prior_thinking_full* and the new thinking as the final thinking in
    ``fin_agents.llm_responses``.

    Args:
        thread_id:               LangGraph thread UUID.
        task_id:                 Governance UUID of the task row.
        task_name:               UI-facing task label.
        node_name:               Owning node name.
        payload:                 Original serialised task input.
        prior_thinking_full:     Complete prior thinking text (for final DB storage).
        prior_thinking_compressed: Compressed prior thinking with repetitions folded.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
        where ``thinking`` is the concatenation of prior and new thinking.
    """
    from langchain_core.messages import HumanMessage as _HM

    builders = _get_stream_prompt_builders()
    if task_name in builders:
        base_messages = builders[task_name](payload)
    else:
        # stream_llm path — rebuild the original messages.
        query = payload.get("query", "")
        stats_analysis = payload.get("stats_analysis", "")
        stats_key_metrics = payload.get("stats_key_metrics", {})
        news_sentiment = payload.get("news_sentiment", "")
        news_highlights: list[str] = payload.get("news_highlights", [])
        highlights_text = "\n".join(f"- {h}" for h in news_highlights) if news_highlights else "No highlights."
        metrics_text = json.dumps(stats_key_metrics, indent=2) if stats_key_metrics else "N/A"
        from langchain_core.messages import SystemMessage as _SM
        system_content = (
            "You are a quantitative financial analyst. Produce structured investment conclusions "
            "based on market research. Respond ONLY with a JSON object (no markdown fences, no extra "
            "text) with exactly these fields:\n"
            '{"summary": "<2-3 sentence overall conclusion>", '
            '"recommendation": "<Buy|Sell|Hold>", '
            '"confidence": "<High|Medium|Low>", '
            '"key_points": ["<point1>", "<point2>", ...], '
            '"risk_factors": ["<risk1>", "<risk2>", ...]}'
        )
        human_content = (
            f"Query: {query}\n\n"
            f"Statistical Analysis:\n{stats_analysis or 'Not available.'}\n\n"
            f"Key Metrics:\n{metrics_text}\n\n"
            f"News Sentiment:\n{news_sentiment or 'Not available.'}\n\n"
            f"News Highlights:\n{highlights_text}"
        )
        base_messages = [_SM(content=system_content), _HM(content=human_content)]

    # Append the compressed prior thinking as continuation context.
    continuation_note = (
        "The previous reasoning attempt stopped with repeated content. "
        "Here is the prior thinking (with repetitions compressed):\n\n"
        f"{prior_thinking_compressed}\n\n"
        "Please continue reasoning from this point without repeating yourself."
    )
    messages = base_messages + [_HM(content=continuation_note)]

    llm = _select_llm(payload.get("query", ""))
    new_result = await _run_stream_core(
        thread_id, task_id, task_name, node_name, payload, messages, llm,
    )

    # Concatenate prior full thinking with the new thinking so the DB row
    # captures the complete reasoning chain across both streaming attempts.
    new_thinking: str | None = new_result.get("thinking")
    if prior_thinking_full and new_thinking:
        combined_thinking = prior_thinking_full + "\n<continuation>\n" + new_thinking
    elif prior_thinking_full:
        combined_thinking = prior_thinking_full
    else:
        combined_thinking = new_thinking

    # Overwrite the just-inserted llm_responses.thinking with the combined value
    # so the stored record reflects the full reasoning chain.
    if combined_thinking != new_thinking:
        from backend.db.postgres.connection import raw_conn
        async with raw_conn() as conn:
            await conn.execute(
                """
                UPDATE fin_agents.llm_responses
                SET thinking = %s
                WHERE id = (
                    SELECT id FROM fin_agents.llm_responses
                    WHERE task_id = %s
                    ORDER BY ts DESC
                    LIMIT 1
                )
                """,
                (combined_thinking, task_id),
            )

    return {**new_result, "thinking": combined_thinking}


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
    return asyncio.run(
        _run_stream_compact_continue_async(
            thread_id, task_id, task_name, node_name, payload,
            prior_thinking_full, prior_thinking_compressed,
        )
    )
