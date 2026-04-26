"""Redis layer error code registry.

Error code prefixes
-------------------
``REDIS_PUBLISH_``    — Pub/Sub publish failures.
``REDIS_STREAM_``     — Redis Streams read/write failures.
``REDIS_LOCK_``       — Distributed lock failures.
``REDIS_SESSION_``    — Session-state key operation failures.
``REDIS_ROUTER_``     — RedisRouter configuration errors.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Pub/Sub ───────────────────────────────────────────────────────────────────

#: PUBLISH to a lifecycle Redis channel failed.
REDIS_PUBLISH_FAILED = "REDIS_PUBLISH_FAILED"

# ── Streams ───────────────────────────────────────────────────────────────────

#: XADD to a Redis stream failed (token or perf stream write).
REDIS_STREAM_WRITE_FAILED = "REDIS_STREAM_WRITE_FAILED"

#: XREAD from a Redis stream failed (SSE generator or subscriber).
REDIS_STREAM_READ_FAILED = "REDIS_STREAM_READ_FAILED"

# ── Distributed lock ──────────────────────────────────────────────────────────

#: Releasing a Redis distributed lock failed.
REDIS_LOCK_RELEASE_FAILED = "REDIS_LOCK_RELEASE_FAILED"

#: Renewing (refreshing TTL of) a Redis distributed lock failed.
REDIS_LOCK_RENEW_FAILED = "REDIS_LOCK_RENEW_FAILED"

# ── Session state ─────────────────────────────────────────────────────────────

#: A session-state key operation (cancel signal, phase, watch, ack-store) failed.
REDIS_SESSION_OP_FAILED = "REDIS_SESSION_OP_FAILED"

# ── Router configuration ──────────────────────────────────────────────────────

#: RedisRouter was constructed with no Redis URLs — at least one is required.
REDIS_ROUTER_NO_URLS = "REDIS_ROUTER_NO_URLS"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each Redis error code to a human-readable description.
REDIS_ERRORS: dict[str, str] = {
    REDIS_PUBLISH_FAILED: (
        "Publishing a lifecycle event to Redis Pub/Sub failed. "
        "The SSE client may not receive this event; it will be replayed on reconnect."
    ),
    REDIS_STREAM_WRITE_FAILED: (
        "Writing a token or batch event to a Redis stream failed. "
        "Some streaming output may be missing from the SSE client."
    ),
    REDIS_STREAM_READ_FAILED: (
        "Reading from a Redis stream failed. "
        "The SSE generator will retry; if persistent, check Redis connectivity."
    ),
    REDIS_LOCK_RELEASE_FAILED: (
        "Releasing a Redis distributed lock failed. "
        "The lock will expire after its TTL; no manual intervention is required."
    ),
    REDIS_LOCK_RENEW_FAILED: (
        "Renewing a Redis distributed lock failed. "
        "The lock may expire before the protected operation completes."
    ),
    REDIS_SESSION_OP_FAILED: (
        "A Redis session-state operation failed. "
        "Session data (cancel signal, query phase, watch target) may be stale."
    ),
    REDIS_ROUTER_NO_URLS: (
        "RedisRouter was initialised without any Redis URLs. "
        "Provide at least one REDIS_URL in the environment configuration."
    ),
}
