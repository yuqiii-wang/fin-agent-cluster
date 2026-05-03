"""centrifugo.client — HTTP API client for publishing events to Centrifugo.

Architecture
------------
Two Centrifugo nodes (centrifugo-0, centrifugo-1) each back a dedicated Redis
shard.  FastAPI uses the same SHA-256 hash of ``thread_id`` as the Redis router
to determine which node to publish to, so the Centrifugo broker (Redis) always
has the full channel history on the correct shard.

The publish call is **fire-and-forget**: errors are logged at WARNING level and
never raised, so a transient Centrifugo outage does not crash the graph.

Scope-based Public API
-----------------------
All four functions publish to the same ``thread:{thread_id}`` Centrifugo channel
(the channel is always scoped to a thread).  The scope distinction is semantic —
it makes call-sites explicit about which lifecycle level the event belongs to and
allows future differentiation (e.g. different retry budgets per scope).

:func:`get_shard_index`      — deterministic shard index (0 or 1) for a thread_id.
:func:`publish_thread_event` — thread-level events: done, query_status, query_received.
:func:`publish_node_event`   — node-level events: node_input, node_output, node_status.
:func:`publish_task_event`   — task-level events: started, completed, failed, cancelled.
:func:`publish_stream_event` — stream-level events: ingest_complete, stream_stopped, stream_complete.
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

# Shared async HTTP client — reused across all publish calls.
# Uses connection pooling for low latency on high-frequency token events.
# keepalive_expiry=20s prevents stale connections after Centrifugo restarts.
_http_client: httpx.AsyncClient | None = None
_HTTP_LIMITS = httpx.Limits(keepalive_expiry=20.0)


def _get_http_client() -> httpx.AsyncClient:
    """Return (lazily creating) the shared async HTTP client.

    Returns:
        Shared :class:`httpx.AsyncClient` with connection pooling and a
        20-second keep-alive expiry to avoid stale connections after a
        Centrifugo node restart.
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=5.0, limits=_HTTP_LIMITS)
    return _http_client


def get_shard_index(thread_id: str) -> int:
    """Return the Centrifugo shard index for *thread_id*.

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


def _node_url(thread_id: str) -> str:
    """Return the Centrifugo internal API base URL for *thread_id*.

    Args:
        thread_id: LangGraph UUID.

    Returns:
        URL string, e.g. ``"http://127.0.0.1:8101"``.
    """
    settings = get_settings()
    if not settings.CENTRIFUGO_NODES:
        raise RuntimeError(f"[{CENTRIFUGO_NO_NODES}] CENTRIFUGO_NODES is empty")
    return settings.CENTRIFUGO_NODES[get_shard_index(thread_id)]


async def _publish_to_channel(thread_id: str, payload: dict[str, Any]) -> None:
    """HTTP transport — publish *payload* to the ``thread:{thread_id}`` Centrifugo channel.

    Internal function shared by all scope-specific publishers.
    Errors are logged at WARNING level and never raised — a transient
    Centrifugo outage must not interrupt the LangGraph execution path.

    Args:
        thread_id: LangGraph thread UUID; determines the shard and channel name.
        payload:   Dict to publish as the channel message data.
    """
    settings = get_settings()
    # Retry once on stale-connection errors (e.g. after a Centrifugo restart
    # the pooled keep-alive TCP connection may be dead, producing an
    # "unexpected EOF" / RemoteProtocolError on the first use).
    _RETRYABLE = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError)
    for attempt in range(2):
        try:
            base = _node_url(thread_id)
            client = _get_http_client()
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
                    "[centrifugo] slow publish event=%s thread_id=%s elapsed_ms=%.0f",
                    payload.get("event", "?"), thread_id, _elapsed_ms,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "[%s] publish failed thread_id=%s status=%d body=%s",
                    CENTRIFUGO_PUBLISH_FAILED,
                    thread_id,
                    resp.status_code,
                    resp.text[:200],
                )
            return
        except _RETRYABLE as exc:  # stale pooled connection — retry once with a fresh client
            if attempt == 0:
                logger.debug(
                    "[%s] stale connection on publish thread_id=%s (%s); retrying",
                    CENTRIFUGO_PUBLISH_FAILED,
                    thread_id,
                    exc,
                )
                # Force-close the pooled client so _get_http_client() creates a new one.
                global _http_client
                if _http_client and not _http_client.is_closed:
                    await _http_client.aclose()
                _http_client = None
                continue
            logger.warning(
                "[%s] publish error thread_id=%s: %s",
                CENTRIFUGO_PUBLISH_FAILED,
                thread_id,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] publish error thread_id=%s: %s",
                CENTRIFUGO_PUBLISH_FAILED,
                thread_id,
                exc,
            )
            return


# ---------------------------------------------------------------------------
# Scope-specific public API
# All four functions publish to the same ``thread:{thread_id}`` channel.
# The scope is semantic — it makes call-sites explicit about the lifecycle
# level of the event.
# ---------------------------------------------------------------------------


async def publish_thread_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a thread-level lifecycle event (done, query_status, query_received, etc.).

    Thread-scoped events represent the overall query session lifecycle.
    The authoritative timestamps come from ``fin_agents.user_queries``.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_channel(thread_id, payload)


async def publish_node_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a node-level lifecycle event (node_input, node_output, node_status).

    Node-scoped events carry timestamps derived from ``fin_agents.node_executions``
    (``started_at`` + ``elapsed_ms``) — not from wall-clock time at emit.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_channel(thread_id, payload)


async def publish_task_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a task-level lifecycle event (started, completed, failed, cancelled).

    Task-scoped events carry timestamps derived from ``fin_agents.tasks``
    (``created_at`` / ``updated_at``) — not from wall-clock time at emit.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_channel(thread_id, payload)


async def publish_stream_event(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a stream-level event (ingest_complete, stream_stopped, stream_complete).

    Stream-scoped events are ephemeral — they are not persisted in PG DB.
    Timestamps in these payloads are wall-clock values from the streaming worker.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_channel(thread_id, payload)


__all__ = [
    "get_shard_index",
    "publish_thread_event",
    "publish_node_event",
    "publish_task_event",
    "publish_stream_event",
]
