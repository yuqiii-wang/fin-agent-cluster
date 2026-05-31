"""httpx_client — centralised HTTP client factory for the backend.

All httpx client creation is routed through this module.  Callers import
make_*_client factory functions and httpx exception types from here; they
do not import ``httpx`` directly.

Factory functions
-----------------
make_ollama_sync_client          — sync Ollama LLM/embed client (loopback proxy bypass).
make_ollama_async_client         — async Ollama LLM/embed client (loopback proxy bypass).
make_fmp_async_client            — async FMP REST API client (auth + proxy from settings).
make_web_browser_async_client    — async web-scraping client (browser simulation headers).
make_centrifugo_sse_async_client — async Centrifugo SSE publish client (keep-alive pool).
make_internal_async_client       — async short-timeout client for internal service probes.
make_mock_transport_async_client — async client with a custom in-process transport.

Re-exported httpx types
-----------------------
Callers that need raw httpx types (exception handling, base class extension,
type annotations) import them from here rather than directly from ``httpx``.
"""

from __future__ import annotations

import httpx

# ---------------------------------------------------------------------------
# Core client types
# ---------------------------------------------------------------------------

AsyncClient = httpx.AsyncClient
Client = httpx.Client

# ---------------------------------------------------------------------------
# Transport / low-level types
# (needed by mock transport subclass, proxy mounts, type annotations)
# ---------------------------------------------------------------------------

AsyncBaseTransport = httpx.AsyncBaseTransport
AsyncHTTPTransport = httpx.AsyncHTTPTransport
Request = httpx.Request
Response = httpx.Response
Limits = httpx.Limits
Timeout = httpx.Timeout

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

HTTPError = httpx.HTTPError
HTTPStatusError = httpx.HTTPStatusError
RequestError = httpx.RequestError
ConnectError = httpx.ConnectError
TimeoutException = httpx.TimeoutException
RemoteProtocolError = httpx.RemoteProtocolError
ReadError = httpx.ReadError

# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

from backend.httpx_client.factory import (  # noqa: E402
    make_ark_async_client,
    make_ark_sync_client,
    make_centrifugo_sse_async_client,
    make_fmp_async_client,
    make_internal_async_client,
    make_mock_transport_async_client,
    make_ollama_async_client,
    make_ollama_sync_client,
    make_web_browser_async_client,
)

# ---------------------------------------------------------------------------
# Browser headers constants
# ---------------------------------------------------------------------------

from backend.httpx_client.browser_headers import (  # noqa: E402
    BROWSER_API_HEADERS,
    BROWSER_HEADERS,
)


__all__ = [
    # Client types
    "AsyncClient",
    "Client",
    # Transport / low-level
    "AsyncBaseTransport",
    "AsyncHTTPTransport",
    "Request",
    "Response",
    "Limits",
    "Timeout",
    # Exceptions
    "HTTPError",
    "HTTPStatusError",
    "RequestError",
    "ConnectError",
    "TimeoutException",
    "RemoteProtocolError",
    "ReadError",
    # Factories
    "make_centrifugo_sse_async_client",
    "make_fmp_async_client",
    "make_internal_async_client",
    "make_mock_transport_async_client",
    "make_ollama_async_client",
    "make_ollama_sync_client",
    "make_web_browser_async_client",
    # Browser headers
    "BROWSER_HEADERS",
    "BROWSER_API_HEADERS",
]
