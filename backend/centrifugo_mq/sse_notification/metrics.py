"""SSE notification Prometheus metrics.

Counters and histograms exposed at ``/metrics`` for auditing the ACK/NACK
rate of every SSE notification topic (thread / node / task scope).

Labels
------
scope  : ``thread`` | ``node`` | ``task``
event  : event name string (e.g. ``done``, ``node_status``, ``task_status``)
reason : (nack only) ``explicit_nack`` | ``exhausted``
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# ── Published ─────────────────────────────────────────────────────────────────
SSE_PUBLISHED = Counter(
    "sse_notification_publish_total",
    "Total SSE notification events published (first attempt; includes fire-and-forget).",
    ["scope", "event"],
)

SSE_PUBLISH_ATTEMPTS = Counter(
    "sse_notification_attempt_total",
    "Total publish attempts across all retries (each re-send increments once).",
    ["scope", "event"],
)

# ── ACK ───────────────────────────────────────────────────────────────────────
SSE_ACK = Counter(
    "sse_notification_ack_total",
    "Total SSE notifications acknowledged by the frontend.",
    ["scope", "event"],
)

# ── NACK ──────────────────────────────────────────────────────────────────────
SSE_NACK = Counter(
    "sse_notification_nack_total",
    "Total SSE notifications not acknowledged. reason=explicit_nack|exhausted.",
    ["scope", "event", "reason"],
)

# ── Latency (ACK path only) ────────────────────────────────────────────────────
SSE_ACK_LATENCY = Histogram(
    "sse_notification_ack_latency_seconds",
    "End-to-end latency from first publish to ACK receipt (seconds).",
    ["scope", "event"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0),
)

__all__ = [
    "SSE_PUBLISHED",
    "SSE_PUBLISH_ATTEMPTS",
    "SSE_ACK",
    "SSE_NACK",
    "SSE_ACK_LATENCY",
]
