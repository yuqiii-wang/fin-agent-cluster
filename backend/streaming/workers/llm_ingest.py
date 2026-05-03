"""Celery worker — LLM streaming ingest task for celery-ingest.

A single worker process consumes from the ``stream:ingest`` queue.
On demand, the worker:

  1. Receives formatted LangChain messages (LangChain-serialised JSON).
  2. Streams the LLM response token-by-token via ``llm.astream``.
  3. XADDs each raw token to ``fin:llm:tokens`` (shard-routed) so Centrifugo's
     native Redis consumer can deliver them to WebSocket clients without
     FastAPI involvement.
  4. After all tokens: XADDs one completion record to ``fin:llm:completions``
     for the ``pg-persist`` beat worker to persist to ``fin_agents.llm_responses``.
  5. Returns the accumulated answer text to the Celery result backend so the
     calling LangGraph node can continue graph execution.

Thinking tokens (reasoning_content / thinking blocks) are stored as raw chunks
in ``fin:llm:tokens`` with ``token_type="thinking"``, never summarised.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from backend.streaming.celery_app import celery_app
from backend.streaming.errors import STREAM_WORKER_BATCH_FAILED
from backend.streaming.schemas import LLMCompletionMessage
from backend.streaming.streams import STREAM_LLM_COMPLETIONS, STREAM_TOKEN, xadd, xadd_sharded

logger = logging.getLogger(__name__)


@celery_app.task(
    name="backend.streaming.workers.llm_ingest.invoke_llm",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def invoke_llm(
    self: Any,
    messages_json: str,
    temperature: float = 0.3,
    thread_id: Optional[str] = None,
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    node_name: Optional[str] = None,
    json_mode: bool = False,
) -> str:
    """Stream the LLM response, publish raw tokens to Redis, return full answer text.

    Each token chunk is XADDed to ``fin:llm:tokens`` (shard-routed by thread_id)
    so Centrifugo's native Redis consumer delivers it to the browser without
    FastAPI involvement.  After streaming completes, one completion record is
    XADDed to ``fin:llm:completions`` for the ``pg-persist`` beat worker.

    Args:
        messages_json: LangChain-serialised messages (via ``langchain_core.load.dumps``).
        temperature:   Sampling temperature.
        thread_id:     Originating LangGraph thread UUID.
        task_id:     UUID of the pre-created task row for token attribution.
        task_name:      Agent sub-task key for usage tracking.
        node_name:     Agent node name for usage tracking.
        json_mode:     Bind JSON response format when the provider supports it.

    Returns:
        Full accumulated answer text (thinking excluded).

    Raises:
        Exception: Re-raised (with retry) on LLM failure.
    """
    try:
        return asyncio.run(
            _stream_invoke(messages_json, temperature, thread_id, task_id, task_name, node_name, json_mode)
        )
    except Exception as exc:
        logger.warning(
            "[%s] invoke_llm failed thread_id=%s: %s",
            STREAM_WORKER_BATCH_FAILED,
            thread_id,
            exc,
        )
        raise self.retry(exc=exc)


async def _stream_invoke(
    messages_json: str,
    temperature: float,
    thread_id: Optional[str],
    task_id: Optional[str],
    task_name: Optional[str],
    node_name: Optional[str],
    json_mode: bool,
) -> str:
    """Stream LLM, XADD raw tokens, XADD completion record, return answer text.

    Args:
        messages_json: LangChain-serialised messages.
        temperature:   Sampling temperature.
        thread_id:     LangGraph thread UUID.
        task_id:     UUID of the task row for token attribution.
        task_name:      Agent sub-task key.
        node_name:     Agent node name.
        json_mode:     Bind JSON response format when supported.

    Returns:
        Full accumulated answer text (thinking excluded).
    """
    from langchain_core.load import loads as lc_loads  # noqa: PLC0415
    from backend.llm import get_active_provider, get_llm  # noqa: PLC0415

    messages = lc_loads(messages_json)
    provider = get_active_provider()
    llm = get_llm(temperature=temperature)
    if json_mode:
        try:
            llm = llm.bind(response_format={"type": "json_object"})
        except Exception:  # noqa: BLE001
            pass

    model_name = _get_model_name(llm)
    prompts_text = _format_messages(messages)
    start_ns = time.monotonic_ns()

    thinking_parts: list[str] = []
    answer_parts: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    async for chunk in llm.astream(messages):
        t_token, a_token = _extract_chunk_tokens(chunk)

        if t_token:
            thinking_parts.append(t_token)
            if thread_id:
                await _xadd_token(thread_id, task_id, task_name, node_name, "thinking", t_token)

        if a_token:
            answer_parts.append(a_token)
            if thread_id:
                await _xadd_token(thread_id, task_id, task_name, node_name, "answer", a_token)

        # Usage metadata is typically only on the final chunk.
        pt, ct = _extract_chunk_usage(chunk)
        if pt or ct:
            prompt_tokens = pt
            completion_tokens = ct

    latency_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    thinking_text = "".join(thinking_parts)
    answer_text = "".join(answer_parts)

    await _publish_completion(
        provider=provider,
        model=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        thread_id=thread_id,
        task_id=task_id,
        task_name=task_name,
        node_name=node_name,
        prompts=prompts_text,
        thinking=thinking_text,
        answer=answer_text,
    )

    return answer_text


async def _xadd_token(
    thread_id: str,
    task_id: Optional[str],
    task_name: Optional[str],
    node_name: Optional[str],
    token_type: str,
    data: str,
) -> None:
    """XADD a single token event to ``fin:llm:tokens`` on the correct shard.

    The stream entry uses two fields as required by Centrifugo v6's async consumer:
    ``method=publish`` and ``payload=<publish request JSON>``.

    Args:
        thread_id:  LangGraph thread UUID (determines shard and channel).
        task_id:  UUID of the task row; ``None`` when not tracked.
        task_name:   Agent sub-task key.
        node_name:  Agent node name.
        token_type: ``"thinking"`` or ``"answer"``.
        data:       Raw token text.
    """
    event: dict[str, Any] = {
        "event": "token",
        "token_type": token_type,
        "data": data,
    }
    if task_id is not None:
        event["task_id"] = task_id
    if task_name:
        event["task_name"] = task_name
    if node_name:
        event["node_name"] = node_name

    payload_value = json.dumps({"channel": f"thread:{thread_id}", "data": event})
    try:
        await xadd_sharded(thread_id, STREAM_TOKEN, {"method": "publish", "payload": payload_value})
    except Exception as exc:  # noqa: BLE001
        logger.debug("[llm_ingest] xadd_token failed: %s", exc)


async def _publish_completion(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    thread_id: Optional[str],
    task_id: Optional[str],
    task_name: Optional[str],
    node_name: Optional[str],
    prompts: Optional[str] = None,
    thinking: Optional[str] = None,
    answer: Optional[str] = None,
) -> None:
    """XADD one LLM completion record to ``fin:llm:completions``.

    Best-effort — never raises.  The ``pg-persist`` beat worker reads this
    stream and persists rows to ``fin_agents.llm_responses``, then XDELs.

    Args:
        provider:          LLM provider name (e.g. ``"ollama"``, ``"ark"``).
        model:             Model identifier.
        prompt_tokens:     Input token count.
        completion_tokens: Output token count.
        latency_ms:        Wall-clock latency in milliseconds.
        thread_id:         LangGraph thread UUID.
        task_id:         UUID of the ``fin_agents.tasks`` row for
                           the optional 1:1 link in ``llm_responses``.
        task_name:          Agent sub-task key.
        node_name:         Agent node name.
        prompts:           Serialised input messages.
        thinking:          Accumulated chain-of-thought text (raw tokens joined).
        answer:            Accumulated final response text (raw tokens joined).
    """
    msg = LLMCompletionMessage(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=latency_ms,
        thread_id=thread_id,
        task_id=task_id,
        task_name=task_name,
        node_name=node_name,
        prompts=prompts,
        thinking=thinking,
        answer=answer,
    )
    try:
        await xadd(STREAM_LLM_COMPLETIONS, msg.model_dump())
    except Exception as exc:  # noqa: BLE001
        logger.debug("[llm_ingest] publish_completion failed: %s", exc)


def _extract_chunk_tokens(chunk: Any) -> tuple[str, str]:
    """Extract (thinking_token, answer_token) from a streaming LLM chunk.

    Handles:
    - ``additional_kwargs.reasoning_content`` / ``thinking`` (DeepSeek / Qwen).
    - Structured content list blocks with ``type='thinking'`` / ``type='text'``
      (Anthropic-style).
    - Plain string ``content`` (standard answer token).

    Args:
        chunk: ``AIMessageChunk`` from LangChain.

    Returns:
        Tuple of ``(thinking_token, answer_token)`` — either may be empty.
    """
    thinking_token = ""
    answer_token = ""

    if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
        rc = (
            chunk.additional_kwargs.get("reasoning_content")
            or chunk.additional_kwargs.get("thinking")
            or ""
        )
        if rc:
            thinking_token = rc

    content = getattr(chunk, "content", "")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "thinking":
                t = block.get("thinking", "") or block.get("text", "")
                if t and not thinking_token:
                    thinking_token = t
            elif btype == "text":
                answer_token += block.get("text", "")
    elif content:
        answer_token = str(content)

    return thinking_token, answer_token


def _extract_chunk_usage(chunk: Any) -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from a streaming chunk.

    Many providers only populate usage on the final chunk.  Returns ``(0, 0)``
    for intermediate chunks.

    Args:
        chunk: ``AIMessageChunk`` from LangChain.

    Returns:
        Tuple of ``(prompt_tokens, completion_tokens)``.
    """
    if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
        meta = chunk.usage_metadata
        return (
            int(meta.get("input_tokens", 0)),
            int(meta.get("output_tokens", 0)),
        )
    if hasattr(chunk, "response_metadata") and chunk.response_metadata:
        u = chunk.response_metadata.get(
            "usage", chunk.response_metadata.get("token_usage", {})
        )
        return (
            int(u.get("prompt_tokens", u.get("input_tokens", 0))),
            int(u.get("completion_tokens", u.get("output_tokens", 0))),
        )
    return 0, 0


def _format_messages(messages: list) -> str:
    """Serialise LangChain messages to a plain-text prompt log.

    Args:
        messages: List of LangChain ``BaseMessage`` instances.

    Returns:
        Newline-separated ``[role]: content`` lines.
    """
    parts: list[str] = []
    for m in messages:
        role = type(m).__name__.replace("Message", "").lower()
        content = getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        parts.append(f"[{role}]: {content}")
    return "\n".join(parts)


def _get_model_name(llm: Any) -> str:
    """Extract the model name string from a LangChain chat model instance.

    Args:
        llm: LangChain ``BaseChatModel`` instance.

    Returns:
        Model name, or empty string if unavailable.
    """
    return (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or ""
    )


