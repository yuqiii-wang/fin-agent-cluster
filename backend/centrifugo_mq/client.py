"""centrifugo.client — HTTP API client for publishing events to Centrifugo.

Architecture
------------
Centrifugo is split into two tiers:

1. **Token-streaming tier** — centrifugo-llm-0 + centrifugo-llm-1.
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

from backend.centrifugo_mq.errors import CENTRIFUGO_NO_NODES, CENTRIFUGO_PUBLISH_FAILED
from backend.config import get_settings
from backend.httpx_client import (
    AsyncClient,
    ConnectError,
    ReadError,
    RemoteProtocolError,
    make_centrifugo_sse_async_client,
)

logger = logging.getLogger(__name__)

# Per-shard HTTP client pool for the SSE lifecycle tier.
# Key: shard index (0 or 1).  Lazily created on first publish to each shard.
_sse_http_clients: dict[int, AsyncClient] = {}
_sse_http_client_loops: dict[int, Any] = {}  # asyncio.AbstractEventLoop | None


def _get_sse_http_client(shard: int) -> AsyncClient:
    """Return (lazily creating) the shared async HTTP client for centrifugo-sse-{shard}.

    Creates a fresh client whenever the running asyncio event loop changes (e.g.
    between Celery tasks that each call ``asyncio.run()``).  Reusing an httpx
    client bound to a closed event loop causes ``Event loop is closed`` errors
    on the next publish attempt.

    Args:
        shard: SSE shard index (0 or 1).

    Returns:
        Shared :class:`~backend.httpx_client.AsyncClient` with connection pooling
        and a 20-second keep-alive expiry to avoid stale connections after a
        Centrifugo node restart.
    """
    import asyncio

    try:
        current_loop: Any = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    existing = _sse_http_clients.get(shard)
    cached_loop = _sse_http_client_loops.get(shard)

    if existing is not None and not existing.is_closed and cached_loop is current_loop:
        return existing

    # Loop changed (Celery asyncio.run recycled the loop) or first access —
    # create a fresh client bound to the current loop.
    _sse_http_clients[shard] = make_centrifugo_sse_async_client()
    _sse_http_client_loops[shard] = current_loop
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


async def _publish_to_sse_channel(thread_id: str, payload: dict[str, Any]) -> None:
    """HTTP transport — publish *payload* to the ``thread:{thread_id}`` channel on centrifugo-sse-{shard}.

    The shard is determined by SHA-256(thread_id) % len(CENTRIFUGO_SSE_NODES), matching
    the shard the frontend subscribes to via the /auth/centrifugo/sse-notification endpoint.

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
    _RETRYABLE = (RemoteProtocolError, ConnectError, ReadError)
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
    """Publish a stream-level lifecycle event (ingest_complete, stream_stopped, stream_complete).

    Stream-scoped events represent the LLM output stream lifecycle within
    a node.  Published to centrifugo-sse via its HTTP API.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict; must include an ``"event"`` key.
    """
    await _publish_to_sse_channel(thread_id, payload)


async def has_app_viewers(thread_id: str) -> bool:
    """Return ``True`` if the user who owns *thread_id* still has the app open.

    Checks the explicit Redis viewer flag (``fin:user:app_viewer:{user_id}``)
    set at query submission time first.  Falls back to Centrifugo
    ``presence_stats`` on the ``user:{user_id}`` channel of the centrifugo-sse
    shard that owns that user.

    The Redis-first strategy eliminates the WebSocket timing race: the flag is
    set synchronously before the graph even starts, whereas the Centrifugo
    presence subscription may not yet be established when ``stream_task`` checks.

    Differs from :func:`has_thread_viewers`:

    * ``has_app_viewers`` — is the user's browser open at all?  ``False`` means
      the browser is closed; skip all SSE publishing and LLM streaming.
    * ``has_thread_viewers`` — is the user actively viewing *this* thread?
      ``False`` means they are on a different thread; still publish SSE (stored
      in Centrifugo history for recovery) but skip LLM token streaming.

    On any error defaults to ``True`` so events are never silently dropped.

    Args:
        thread_id: LangGraph thread UUID (used to look up the owning user).

    Returns:
        ``True`` if at least one client is viewing the app;
        ``False`` if the user has no open browser session.
    """
    from backend.db.redis.session.thread_user_store import get_user_id_for_thread
    from backend.db.redis.session.viewer_store import has_app_viewer

    user_id = await get_user_id_for_thread(thread_id)
    if user_id is None:
        return True  # Cannot determine owner — safe default.

    # Primary: explicit Redis flag set at query submission or viewer registration.
    if await has_app_viewer(user_id):
        return True

    # Secondary fallback: Centrifugo presence stats (covers reconnects / tab
    # reopens where the Redis flag may have been set before a new session).
    settings = get_settings()
    if not settings.CENTRIFUGO_SSE_NODES:
        return True
    shard = get_sse_shard_index(user_id)
    try:
        base = settings.CENTRIFUGO_SSE_NODES[shard]
        client = _get_sse_http_client(shard)
        resp = await client.post(
            f"{base}/api",
            headers={
                "Authorization": f"apikey {settings.CENTRIFUGO_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "method": "presence_stats",
                "params": {"channel": f"user:{user_id}"},
            },
        )
        if resp.status_code >= 400:
            return True
        data = resp.json()
        num_clients: int = data.get("result", {}).get("num_clients", 0)
        return num_clients > 0
    except Exception:  # noqa: BLE001
        return True


async def has_thread_viewers(thread_id: str) -> bool:
    """Return ``True`` if any frontend client is actively viewing *thread_id*.

    Checks the explicit Redis viewer flag (``fin:thread:viewer:{thread_id}``)
    set at query submission time first.  Falls back to Centrifugo
    ``presence_stats`` on the ``thread:{thread_id}`` channel of centrifugo-sse.

    The Redis-first strategy eliminates the WebSocket timing race: the flag is
    set synchronously before the graph even starts, whereas the Centrifugo
    ``thread:`` subscription may not be established when ``stream_task`` checks.

    On any error the function defaults to ``True`` so SSE notifications are
    not silently swallowed when the check itself fails.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if at least one client is subscribed; ``False`` otherwise.
    """
    from backend.db.redis.session.viewer_store import has_thread_viewer

    # Primary: explicit Redis flag.
    if await has_thread_viewer(thread_id):
        return True

    # Secondary fallback: Centrifugo presence stats.
    settings = get_settings()
    if not settings.CENTRIFUGO_SSE_NODES:
        return True  # Safe default — assume viewers present.
    shard = get_sse_shard_index(thread_id)
    try:
        base = settings.CENTRIFUGO_SSE_NODES[shard]
        client = _get_sse_http_client(shard)
        resp = await client.post(
            f"{base}/api",
            headers={
                "Authorization": f"apikey {settings.CENTRIFUGO_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "method": "presence_stats",
                "params": {"channel": f"thread:{thread_id}"},
            },
        )
        if resp.status_code >= 400:
            return True  # Safe default on API error.
        data = resp.json()
        num_clients: int = data.get("result", {}).get("num_clients", 0)
        return num_clients > 0
    except Exception:  # noqa: BLE001
        return True  # Safe default on network error.


__all__ = [
    "get_shard_index",
    "get_sse_shard_index",
    "publish_thread_event",
    "publish_node_event",
    "publish_task_event",
    "publish_stream_event",
    "has_app_viewers",
    "has_thread_viewers",
]
