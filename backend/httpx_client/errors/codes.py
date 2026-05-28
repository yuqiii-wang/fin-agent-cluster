"""Error codes for the httpx_client module."""

from __future__ import annotations

HTTPX_CONNECTION_FAILED: str = "HTTPX_001"
"""Could not establish a TCP connection to the target host."""

HTTPX_TIMEOUT: str = "HTTPX_002"
"""Request exceeded the configured timeout."""

HTTPX_HTTP_ERROR: str = "HTTPX_003"
"""Server returned a 4xx or 5xx HTTP status code."""

HTTPX_REQUEST_FAILED: str = "HTTPX_004"
"""Generic request failure (network error, protocol error, etc.)."""

__all__ = [
    "HTTPX_CONNECTION_FAILED",
    "HTTPX_TIMEOUT",
    "HTTPX_HTTP_ERROR",
    "HTTPX_REQUEST_FAILED",
]
