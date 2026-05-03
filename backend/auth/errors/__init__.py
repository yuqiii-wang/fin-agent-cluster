"""backend.auth.errors — authentication layer error codes."""

from __future__ import annotations

from backend.auth.errors.codes import (
    AUTH_ERRORS,
    AUTH_GUEST_CREATE_FAILED,
    AUTH_INVALID_TOKEN,
)

__all__ = [
    "AUTH_ERRORS",
    "AUTH_GUEST_CREATE_FAILED",
    "AUTH_INVALID_TOKEN",
]
