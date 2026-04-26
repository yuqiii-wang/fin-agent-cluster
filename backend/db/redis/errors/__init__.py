"""Redis layer error code registry package.

Re-exports all error code constants and the ``REDIS_ERRORS`` description dict::

    from backend.db.redis.errors import (
        REDIS_ERRORS,
        REDIS_PUBLISH_FAILED,
        REDIS_STREAM_WRITE_FAILED,
        REDIS_STREAM_READ_FAILED,
        REDIS_LOCK_RELEASE_FAILED,
        REDIS_LOCK_RENEW_FAILED,
        REDIS_SESSION_OP_FAILED,
        REDIS_ROUTER_NO_URLS,
    )
"""

from __future__ import annotations

from backend.db.redis.errors.codes import (
    REDIS_ERRORS,
    REDIS_PUBLISH_FAILED,
    REDIS_STREAM_WRITE_FAILED,
    REDIS_STREAM_READ_FAILED,
    REDIS_LOCK_RELEASE_FAILED,
    REDIS_LOCK_RENEW_FAILED,
    REDIS_SESSION_OP_FAILED,
    REDIS_ROUTER_NO_URLS,
)

__all__ = [
    "REDIS_ERRORS",
    "REDIS_PUBLISH_FAILED",
    "REDIS_STREAM_WRITE_FAILED",
    "REDIS_STREAM_READ_FAILED",
    "REDIS_LOCK_RELEASE_FAILED",
    "REDIS_LOCK_RENEW_FAILED",
    "REDIS_SESSION_OP_FAILED",
    "REDIS_ROUTER_NO_URLS",
]
