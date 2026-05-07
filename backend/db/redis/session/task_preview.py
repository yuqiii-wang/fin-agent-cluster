"""Redis-backed task preview buffer — opt-in streaming for analysis/report nodes.

Each opt-in streaming task buffers its tokens in a Redis List::

    Key:  preview_tokens:{thread_id}:{task_id}   (TTL 30 min)
    Val:  ordered list of token strings

The "live" flag signals that the user has opted in to live streaming::

    Key:  preview_live:{thread_id}:{task_id}     (TTL 30 min)
    Val:  "1"

Workflow
--------
1. Task generates tokens → ``store_preview_token()`` appends to the list.
2. After each batch the task calls ``is_task_stream_live()`` — if the flag is
   set it forwards the batch to Centrifugo immediately.
3. User clicks "enable stream" in the UI → ``POST .../tasks/{task_id}/enable-stream``
   → ``enable_task_stream()`` sets the live flag.
4. On task completion / cancellation / failure → ``cleanup_task_preview()``
   deletes both keys.
"""

from __future__ import annotations

from backend.db.redis.router import get_redis_router

_TOKEN_PREFIX: str = "preview_tokens:"
_LIVE_PREFIX: str = "preview_live:"
_TTL: int = 1800  # 30 minutes


def _token_key(thread_id: str, task_id: str) -> str:
    """Return the Redis List key for the preview token buffer."""
    return f"{_TOKEN_PREFIX}{thread_id}:{task_id}"


def _live_key(thread_id: str, task_id: str) -> str:
    """Return the Redis String key for the live-stream flag."""
    return f"{_LIVE_PREFIX}{thread_id}:{task_id}"


async def store_preview_token(thread_id: str, task_id: str, token: str) -> None:
    """Append *token* to the preview buffer for this task.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task invocation UUID.
        token:     Token string to buffer.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = _token_key(thread_id, task_id)
    pipe = client.pipeline()
    pipe.rpush(key, token)
    pipe.expire(key, _TTL)
    await pipe.execute()


async def is_task_stream_live(thread_id: str, task_id: str) -> bool:
    """Return ``True`` if the user has opted in to live streaming for this task.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task invocation UUID.

    Returns:
        ``True`` when the live flag is set in Redis.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    val = await client.get(_live_key(thread_id, task_id))
    return val is not None


async def enable_task_stream(thread_id: str, task_id: str) -> None:
    """Set the live flag so the task starts forwarding tokens to Centrifugo.

    Called by the ``POST .../tasks/{task_id}/enable-stream`` API endpoint when
    the user opens the task output panel.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task invocation UUID.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    await client.setex(_live_key(thread_id, task_id), _TTL, "1")


async def cleanup_task_preview(thread_id: str, task_id: str) -> None:
    """Delete the preview token buffer and live flag for this task.

    Called by the task runner on completion, cancellation, or failure.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   Task invocation UUID.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    await client.delete(
        _token_key(thread_id, task_id),
        _live_key(thread_id, task_id),
    )


__all__ = [
    "store_preview_token",
    "is_task_stream_live",
    "enable_task_stream",
    "cleanup_task_preview",
]
