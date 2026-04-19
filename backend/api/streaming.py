"""FastAPI router — HTTP / SSE bridge to Redis Streams.

Exposes Redis Streams as an HTTP API for Kong and internal tooling.
All write paths (token publishing, lifecycle events) happen in-process via
``backend.db.redis.publisher`` and ``backend.db.postgres.notifier``;
the UI never publishes to streams directly.

Endpoints
---------
GET  /streaming/sse/{stream_key}
    Subscribe to a named topic stream as an SSE event source.  For per-query
    token + lifecycle events, use ``/api/v1/stream/{thread_id}`` instead.

GET  /streaming/poll/{stream_key}
    HTTP long-poll: block up to ``block_ms`` milliseconds for the next
    batch of messages, then return as JSON.  Useful for internal workers
    or debugging.

GET  /streaming/info/{stream_key}
    Return metadata about a stream (length, name).

Kong routes this router at ``/api/v1/streaming`` with
``response_buffering: false`` on the SSE route so events are flushed
immediately through the proxy.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from backend.streaming.schemas import (
    StreamInfoResponse,
    StreamKey,
)
from backend.streaming.streams import (
    STREAM_KEY_MAP,
    xlen,
    xread,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streaming", tags=["streaming"])

# Max messages returned in a single HTTP poll response.
_POLL_MAX_COUNT = 100
# Default block duration for long-poll (milliseconds).
_POLL_DEFAULT_BLOCK_MS = 5000


def _resolve_stream(stream_key: StreamKey) -> str:
    """Translate a :class:`StreamKey` enum value to an internal stream name.

    Args:
        stream_key: Validated enum value from the request path or body.

    Returns:
        Internal Redis stream name string.

    Raises:
        :class:`fastapi.HTTPException` 400 if the key cannot be resolved
        (should not happen in practice as the enum is exhaustive).
    """
    name = STREAM_KEY_MAP.get(stream_key.value)
    if not name:
        raise HTTPException(status_code=400, detail=f"Unknown stream key: {stream_key.value}")
    return name


# ---------------------------------------------------------------------------
# GET /streaming/sse/{stream_key}
# ---------------------------------------------------------------------------


@router.get("/sse/{stream_key}")
async def sse_consume(
    stream_key: StreamKey,
    last_id: Annotated[Optional[str], Query(description="Resume from this message ID (default: '>' = new messages only)")] = None,
) -> EventSourceResponse:
    """Subscribe to a Redis Stream as a Server-Sent Events source.

    Uses plain XREAD (not a consumer group) so every connected SSE client
    independently tracks its own cursor and receives a full copy of each
    message (true fan-out delivery).  Consumer groups are reserved for the
    Celery workers that need competing-consumer semantics.

    Query params:
        last_id: Optional message ID to resume from.  Omit to receive only
                 new messages.  Use ``'0'`` to replay from the stream start.

    Returns:
        An SSE stream that emits one ``data: <json>`` event per message.
    """
    stream = _resolve_stream(stream_key)

    async def _generator() -> AsyncGenerator[dict, None]:
        """Yield SSE events from the stream until the client disconnects."""
        # "$" means "only messages published after this call" — no replay.
        # Callers pass an explicit last_id to resume from a known offset.
        cursor = last_id if last_id else "$"

        while True:
            try:
                messages = await xread(stream, last_id=cursor, count=50, block_ms=2000)
                for msg_id, fields in messages:
                    cursor = msg_id  # advance per-connection cursor
                    yield {"event": stream_key.value, "data": json.dumps({"id": msg_id, **fields})}
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[streaming.sse] error stream=%s: %s", stream, exc)
                await asyncio.sleep(1)

    return EventSourceResponse(_generator())


# ---------------------------------------------------------------------------
# GET /streaming/poll/{stream_key}
# ---------------------------------------------------------------------------


@router.get("/poll/{stream_key}")
async def poll_consume(
    stream_key: StreamKey,
    last_id: Annotated[str, Query(description="Exclusive lower-bound message ID")] = "0",
    count: Annotated[int, Query(ge=1, le=_POLL_MAX_COUNT)] = 10,
    block_ms: Annotated[int, Query(ge=0, le=30000)] = _POLL_DEFAULT_BLOCK_MS,
) -> dict:
    """Long-poll for new messages from a Redis Stream.

    Returns up to *count* messages newer than *last_id*, blocking for up
    to *block_ms* milliseconds if the stream is empty.

    Query params:
        last_id:  Exclusive lower-bound message ID (default ``'0'`` = from start).
        count:    Max messages per response (1–100, default 10).
        block_ms: Block duration in ms (0–30000, default 5000).

    Returns:
        ``{messages: [{id, ...fields}], next_id: str}`` where ``next_id``
        is the last returned message ID the client should pass on the next call.
    """
    stream = _resolve_stream(stream_key)
    from backend.streaming.streams import xread as _xread

    try:
        messages = await _xread(stream, last_id=last_id, count=count, block_ms=block_ms)
    except Exception as exc:
        logger.error("[streaming.poll] xread failed stream=%s: %s", stream, exc)
        raise HTTPException(status_code=503, detail="Stream read failed") from exc

    items = [{"id": msg_id, **fields} for msg_id, fields in messages]
    next_id = messages[-1][0] if messages else last_id

    return {"messages": items, "next_id": next_id, "count": len(items)}


# ---------------------------------------------------------------------------
# GET /streaming/info/{stream_key}
# ---------------------------------------------------------------------------


@router.get("/info/{stream_key}", response_model=StreamInfoResponse)
async def stream_info(stream_key: StreamKey) -> StreamInfoResponse:
    """Return metadata for a stream.

    Args:
        stream_key: Stream identifier from :class:`StreamKey`.

    Returns:
        :class:`StreamInfoResponse` with ``stream_key``, ``stream``, ``length``.
    """
    stream = _resolve_stream(stream_key)
    try:
        length = await xlen(stream)
    except Exception:
        length = 0

    return StreamInfoResponse(
        stream_key=stream_key,
        stream=stream,
        length=length,
    )
