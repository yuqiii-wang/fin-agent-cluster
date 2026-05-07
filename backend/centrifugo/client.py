"""centrifugo.client — HTTP API client for publishing events to Centrifugo.

Architecture
------------
Centrifugo is split into two tiers:

1. **Token-streaming tier** — centrifugo-token-0 + centrifugo-token-1.
   Each node backs a dedicated Redis shard.  LLM tokens flow here via Centrifugo's
   built-in Redis Stream consumer (``fin:llm:tokens``).  FastAPI does NOT publish
   to these nodes directly.

2. **SSE lifecycle tier** — centrifugo-sse-0 + centrifugo-sse-1.
   All lifecycle events published by FastAPI (started, completed, done, query_*,
   node_*, stream_*) are sent to the shard determined by SHA-256(thread_id) % 2.
   Each shard has its own dedicated Redis backend.

The publish call is **fire-and-forget**: errors are logged at WARNING level and
never raised, so a transient Centrifugo outage does not crash the graph.

Public API
----------
:func:`get_shard_index`      — deterministic shard index (0 or 1) for a thread_id.
                               Used by the auth endpoint to return the correct
                               token-stream WebSocket URL to the frontend.
:func:`get_sse_shard_index`  — deterministic SSE shard index (0 or 1) for a thread_id.
                               Used by the auth endpoint and publish functions.
:func:`publish_thread_event` — thread-level events → centrifugo-sse-{shard}.
:func:`publish_node_event`   — node-level events → centrifugo-sse-{shard}.
:func:`publish_task_event`   — task-level events → centrifugo-sse-{shard}.
:func:`publish_stream_event` — stream-level events → centrifugo-sse-{shard}.
"""

from __future__ import annotations

import hashlib
import logging
import time as _time
from typing import Any

import httpx

from backend.centrifugo.errors import CENTRIFUGO_NO_NODES, CENTRIFUGO_PUBLISH_FAILED
from backend.config import get_settings

logger = logging.getLogger(__name__)

# Per-shard HTTP client pool for the SSE lifecycle tier.
# Key: shard index (0 or 1).  Lazily created on first publish to each shard.
_sse_http_clients: dict[int, httpx.AsyncClient] = {}
_HTTP_LIMITS = httpx.Limits(keepalive_expiry=20.0)


def _get_sse_http_client(shard: int) -> httpx.AsyncClient:
    """Return (lazily creating) the shared async HTTP client for centrifugo-sse-{shard}.

    Args:
        shard: SSE shard index (0 or 1).

    Returns:
        Shared :class:`httpx.AsyncClient` with connection pooling and a
        20-second keep-alive expiry to avoid stale connections after a
        Centrifugo node restart.
    """
    global _sse_http_clients
    client = _sse_http_clients.get(shard)
    if client is None or client.is_closed:
        _sse_http_clients[shard] = httpx.AsyncClient(timeout=5.0, limits=_HTTP_LIMITS)
    return _sse_http_clients[shard]


def get_shard_index(thread_id: str) -> int:
    """Return the Centrifugo token-stream shard index for *thread_id*.

    Uses the same SHA-256 modulo routing as :class:`~backend.db.redis.router.RedisRouter`
    so the Centrifugo node selected here is always backed by the Redis node
    that stores the thread's session keys.

    Args:
        thread_id: LangGraph UUID string.

    Returns:
        Integer shard index (0 or 1) based on node count from settings.
    """
    settings = get_settings()
    n = len(settings.CENTRIFUGO_NODES) or 1
    digest = int(hashlib.sha256(thread_id.encode()).hexdigest(), 16)
    return digest % n


def get_sse_shard_index(thread_id: str) -> int:
    """Return the Centrifugo SSE lifecycle shard index for *thread_id*.

    Uses the same SHA-256 modulo routing so the same thread always publishes
    to and subscribes from the same centrifugo-sse-{n} node.

    Args:
        thread_id: LangGraph UUID string.

    Returns:
        Integer shard index (0 or 1) based on SSE node count from settings.
    """
    settings = get_settings()
    n = len(settings.CENTRIFUGO_SSE_NODES) or 1
    digest = int(hashlib.sha256(thread_id.encode()).hexdigest(), 16)
    return digest % n


def _node_url(thread_id: str) -> str:
    """Return the Centrifugo token-stream internal API base URL for *thread_id*.

    Args:
        thread_id: LangGraph UUID.

    Returns:
        URL string, e.g. ``"http://127.0.0.1:8101"``.
    """
    settings = get_settings()
    if not settings.CENTRIFUGO_NODES:
        raise RuntimeError(f"[{CENTRIFUGO_NO_NODES}] CENTRIFUGO_NODES is empty")
    return settings.CENTRIFUGO_NODES[get_shard_index(thread_id)]


async def _publish_to_sse_channel(thread_id: str, payload: dict[str, Any]) -> None:
    """HTTP transport — publish *payload* to the ``thread:{thread_id}`` channel on centrifugo-sse-{shard}.

    The shard is determined by SHA-256(thread_id) % len(CENTRIFUGO_SSE_NODES), matching
    the shard the frontend subscribes to via the /auth/centrifugo/sse-token endpoint.

    Errors are logged at WARNING level and never raised — a transient
    Centrifugo outage must not interrupt the LangGraph execution path.

    Args:
        thread_id: LangGraph thread UUID; determines the channel name and shard.
        payload:   Dict to publish as the channel message data.
    """
    settings = get_settings()
    if not settings.CENTRIFUGO_SSE_NODES:
        raise RuntimeError(f"[{CENTRIFUGO_NO_NODES}] CENTRIFUGO_SSE_NODES is empty")
    shard = get_sse_shard_index(thread_id)
    _RETRYABLE = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError)
    for attempt in range(2):
        try:
            base = settings.CENTRIFUGO_SSE_NODES[shard]
            client = _get_sse_http_client(shard)
            _t0 = _time.perf_counter()
            resp = await client.post(
                f"{base}/api",
                headers={
                    "Authorization": f"apikey {settings.CENTRIFUGO_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "method": "publish",
                    "params": {
                        "channel": f"thread:{thread_id}",
                        "data": payload,
                    },
                },
            )
            _elapsed_ms = (_time.perf_counter() - _t0) * 1000
            if _elapsed_ms > 200:
                logger.warning(
                    "[centrifugo-sse-%d] slow publish event=%s thread_id=%s elapsed_ms=%.0f",
                    shard, payload.get("event", "?"), thread_id, _elapsed_ms,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "[%s] sse publish failed shard=%d thread_id=%s status=%d body=%s",
                    CENTRIFUGO_PUBLISH_FAILED,
                    shard,
                    thread_id,
                    resp.status_code,
                    resp.text[:200],
                )
            return
        except _RETRYABLE as exc:
            if attempt == 0:
                logger.debug(
                    "[%s] stale connection on sse publish shard=%d thread_id=%s (%s); retrying",
                    CENTRIFUGO_PUBLISH_FAILED,
                    shard,
                    thread_id,
                    exc,
                )
                client = _sse_http_clients.get(shard)
                if client and not client.is_closed:
                    await client.aclose()
                _sse_http_clients.pop(shard, None)
                continue
            logger.warning(
                "[%s] sse publish error shard=%d thread_id=%s: %s",
                CENTRIFUGO_PUBLISH_FAILED,
                shard,
                thread_id,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] sse publish error shard=%d thread_id=%s: %s",
                CENTRIFUGO_PUBLISH_FAILED,
                shard,
                thread_id,
                exc,
            )
            return


# ---------------------------------------------------------------------------
# Scope-specific public API
# All four functions publish to the ``thread:{thread_id}`` channel on centrifugo-sse.
# The scope is semantic — it makes call-sites explicit about the lifecycle
# level of the event.
# ---------------------------------------------------------------------------


async def publish_thread_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a thread-level lifecycle event (done, query_status, query_received, etc.).

    Thread-scoped events represent the overall query session lifecycle.
    The authoritative timestamps come from ``fin_agents.user_queries``.
    Published to centrifugo-sse via its HTTP API.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_sse_channel(thread_id, payload)


async def publish_node_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a node-level lifecycle event (node_input, node_output, node_status).

    Node-scoped events carry timestamps derived from ``fin_agents.node_executions``
    (``started_at`` + ``elapsed_ms``) — not from wall-clock time at emit.
    Published to centrifugo-sse via its HTTP API.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_sse_channel(thread_id, payload)


async def publish_task_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a task-level lifecycle event (started, completed, failed, cancelled).

    Task-scoped events carry timestamps derived from ``fin_agents.tasks``
    (``created_at`` / ``updated_at``) — not from wall-clock time at emit.
    Published to centrifugo-sse via its HTTP API.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_sse_channel(thread_id, payload)


async def publish_stream_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a stream-level event (ingest_complete, stream_stopped, stream_complete).

    Stream-scoped events are ephemeral — they are not persisted in PG DB.
    Timestamps in these payloads are wall-clock values from the streaming worker.
    Published to centrifugo-sse via its HTTP API.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_sse_channel(thread_id, payload)


__all__ = [
    "get_shard_index",
    "publish_thread_event",
    "publish_node_event",
    "publish_task_event",
    "publish_stream_event",
]
