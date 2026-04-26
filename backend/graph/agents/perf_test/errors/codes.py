"""Perf-test agent error code registry.

These codes are passed as ``error_code=`` to :func:`~backend.sse_notifications.fail_task`
or embedded in node-level error payloads.

Error code prefixes
-------------------
``PT_``   — Performance-test specific failures (node-level).

Note: the shared SSE-level codes ``PERF_INGEST_FAILED``, ``PERF_PUBLISH_FAILED``,
``PERF_INGEST_TIMEOUT``, ``PERF_CELERY_REVOKED``, and
``PERF_LOCUST_STREAM_INTERRUPTED`` live in
:mod:`backend.streaming.lifecycle.errors.codes`.
"""

from __future__ import annotations

# Re-export shared SSE-level codes so callers can import from one place.
from backend.streaming.lifecycle.errors import (  # noqa: F401
    PERF_CELERY_REVOKED,
    PERF_INGEST_FAILED,
    PERF_INGEST_TIMEOUT,
    PERF_LOCUST_STREAM_INTERRUPTED,
    PERF_PUBLISH_FAILED,
)

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: Perf-test was stopped by an explicit user stop signal mid-run.
PT_STOP_REQUESTED = "PT_STOP_REQUESTED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each PT node error code to a human-readable description.
PT_AGENT_ERRORS: dict[str, str] = {
    PT_STOP_REQUESTED: (
        "The performance test was stopped by a user-initiated stop signal. "
        "Results up to the stop point may be partially available."
    ),
}
