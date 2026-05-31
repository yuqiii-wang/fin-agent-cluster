"""httpx client factory functions.

Every factory returns a pre-configured :class:`httpx.AsyncClient` or
:class:`httpx.Client`.  Callers use the returned object directly as a context
manager or hold it long-lived; they do not instantiate httpx clients directly.

Proxy handling for Ollama
--------------------------
Ollama typically runs on localhost.  When ``HTTP_PROXY`` is set, loopback
destinations (``localhost``, ``127.0.0.1``, ``::1``) are never routed through
the proxy so the locally-running Ollama instance is always reachable without
proxy configuration.
"""

from __future__ import annotations

import urllib.parse

import httpx

from backend.config import get_settings

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
"""Hostnames for which proxy routing is always skipped."""

_CENTRIFUGO_HTTP_LIMITS = httpx.Limits(keepalive_expiry=20.0)
"""Keep-alive settings for the long-lived Centrifugo SSE publish client."""


def _resolve_loopback_proxy(base_url: str, proxy: str | None) -> str | None:
    """Return *proxy*, or ``None`` when *base_url* resolves to a loopback host.

    Args:
        base_url: Target base URL, e.g. ``"http://localhost:11434"``.
        proxy:    HTTP proxy URL, e.g. ``"http://127.0.0.1:7890"``.

    Returns:
        *proxy* unchanged, or ``None`` when the hostname is loopback.
    """
    if not proxy:
        return None
    host = urllib.parse.urlparse(base_url).hostname or ""
    return None if host in _LOOPBACK_HOSTS else proxy


def make_ollama_sync_client(
    base_url: str,
    proxy: str | None = None,
    timeout_seconds: float = 120.0,
) -> httpx.Client:
    """Create a synchronous httpx client for Ollama endpoints.

    Automatically bypasses *proxy* when *base_url* points to a loopback address.

    Args:
        base_url:        Ollama base URL, e.g. ``"http://localhost:11434"``.
        proxy:           Optional HTTP proxy URL.  Pass ``settings.HTTP_PROXY``.
        timeout_seconds: Total request timeout in seconds.  Default 120 s
                         (suitable for warmup / embed calls).

    Returns:
        Configured :class:`httpx.Client` — use as a context manager.
    """
    resolved = _resolve_loopback_proxy(base_url, proxy)
    return httpx.Client(proxy=resolved, timeout=httpx.Timeout(timeout_seconds))


def make_ollama_async_client(
    base_url: str,
    proxy: str | None = None,
    timeout_seconds: float = 300.0,
) -> httpx.AsyncClient:
    """Create an asynchronous httpx client for Ollama endpoints.

    Automatically bypasses *proxy* when *base_url* points to a loopback address.
    Suitable for long-running streaming or non-streaming chat calls.

    Args:
        base_url:        Ollama base URL, e.g. ``"http://localhost:11434"``.
        proxy:           Optional HTTP proxy URL.  Pass ``settings.HTTP_PROXY``.
        timeout_seconds: Total request timeout in seconds.  Default 300 s
                         (suitable for full LLM generation).

    Returns:
        Configured :class:`httpx.AsyncClient` — use as a context manager.
    """
    resolved = _resolve_loopback_proxy(base_url, proxy)
    return httpx.AsyncClient(proxy=resolved, timeout=httpx.Timeout(timeout_seconds))


def make_fmp_async_client() -> httpx.AsyncClient:
    """Create an async httpx client pre-configured for the FMP REST API.

    Reads ``FMP_BASE_URL``, ``FMP_API_KEY``, and ``HTTP_PROXY`` from application
    settings.  The ``apikey`` query parameter is injected automatically on every
    request so callers do not need to pass it manually.

    Returns:
        Configured :class:`httpx.AsyncClient` — use as a context manager or
        hold long-lived (call ``aclose()`` when done).
    """
    settings = get_settings()
    proxy_url = settings.HTTP_PROXY
    mounts: dict[str, httpx.AsyncBaseTransport] | None = None
    if proxy_url:
        proxy_transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
        mounts = {"https://": proxy_transport, "http://": proxy_transport}
    return httpx.AsyncClient(
        base_url=settings.FMP_BASE_URL,
        params={"apikey": settings.FMP_API_KEY},
        mounts=mounts,
        timeout=15.0,
    )


def make_web_browser_async_client() -> httpx.AsyncClient:
    """Create an async httpx client that simulates a real browser request.

    Sets full browser navigation headers (User-Agent, Accept, Sec-Fetch-* etc.),
    follows HTTP redirects, and routes through ``HTTP_PROXY`` when configured.

    Returns:
        Configured :class:`httpx.AsyncClient` — use as a context manager or
        hold long-lived (call ``aclose()`` when done).
    """
    from backend.httpx_client.browser_headers import BROWSER_HEADERS

    settings = get_settings()
    mounts: dict[str, httpx.AsyncBaseTransport] | None = None
    if settings.HTTP_PROXY:
        proxy_transport = httpx.AsyncHTTPTransport(proxy=settings.HTTP_PROXY)
        mounts = {"https://": proxy_transport, "http://": proxy_transport}
    return httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        timeout=30.0,
        follow_redirects=True,
        mounts=mounts,
    )


def make_centrifugo_sse_async_client() -> httpx.AsyncClient:
    """Create an async httpx client for Centrifugo SSE lifecycle publish calls.

    Uses a 5-second timeout and connection pooling with 20-second keep-alive to
    avoid per-publish TCP overhead against a long-running Centrifugo node.

    Returns:
        Configured :class:`httpx.AsyncClient` — hold long-lived and reuse
        across multiple publishes to the same shard.
    """
    return httpx.AsyncClient(timeout=5.0, limits=_CENTRIFUGO_HTTP_LIMITS)


def make_internal_async_client() -> httpx.AsyncClient:
    """Create an async httpx client for internal service probes (health checks etc.).

    Uses a short 3-second timeout.  No proxy — internal calls should always
    be direct.

    Returns:
        Configured :class:`httpx.AsyncClient` — use as a context manager.
    """
    return httpx.AsyncClient(timeout=3.0)


def make_ark_sync_client(
    proxy: str | None = None,
    timeout_seconds: float = 120.0,
) -> httpx.Client:
    """Create a synchronous httpx client for the ARK (Volcano Engine / Doubao) API.

    ARK is a remote endpoint so proxy is always honoured (no loopback bypass).

    Args:
        proxy:           Optional HTTP proxy URL.  Pass ``settings.HTTP_PROXY``.
        timeout_seconds: Total request timeout in seconds.

    Returns:
        Configured :class:`httpx.Client` — use as a context manager.
    """
    return httpx.Client(proxy=proxy, timeout=httpx.Timeout(timeout_seconds))


def make_ark_async_client(
    proxy: str | None = None,
    timeout_seconds: float = 120.0,
) -> httpx.AsyncClient:
    """Create an asynchronous httpx client for the ARK (Volcano Engine / Doubao) API.

    ARK is a remote endpoint so proxy is always honoured (no loopback bypass).

    Args:
        proxy:           Optional HTTP proxy URL.  Pass ``settings.HTTP_PROXY``.
        timeout_seconds: Total request timeout in seconds.

    Returns:
        Configured :class:`httpx.AsyncClient` — use as a context manager.
    """
    return httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(timeout_seconds))


def make_mock_transport_async_client(
    base_url: str,
    transport: httpx.AsyncBaseTransport,
) -> httpx.AsyncClient:
    """Create an async httpx client backed by a custom in-process transport.

    Used for mock or testing transports that intercept requests without
    performing real network I/O.

    Args:
        base_url:   Base URL prefix for requests, e.g. ``"http://mock-stats"``.
        transport:  :class:`httpx.AsyncBaseTransport` subclass instance.

    Returns:
        :class:`httpx.AsyncClient` wired to *transport*.
    """
    return httpx.AsyncClient(base_url=base_url, transport=transport)


__all__ = [
    "make_ark_async_client",
    "make_ark_sync_client",
    "make_centrifugo_sse_async_client",
    "make_fmp_async_client",
    "make_internal_async_client",
    "make_mock_transport_async_client",
    "make_ollama_async_client",
    "make_ollama_sync_client",
    "make_web_browser_async_client",
]
