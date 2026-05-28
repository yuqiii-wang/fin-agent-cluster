"""errors sub-package for httpx_client."""

from __future__ import annotations

from backend.httpx_client.errors.codes import (
    HTTPX_CONNECTION_FAILED,
    HTTPX_HTTP_ERROR,
    HTTPX_REQUEST_FAILED,
    HTTPX_TIMEOUT,
)

__all__ = [
    "HTTPX_CONNECTION_FAILED",
    "HTTPX_HTTP_ERROR",
    "HTTPX_REQUEST_FAILED",
    "HTTPX_TIMEOUT",
]
