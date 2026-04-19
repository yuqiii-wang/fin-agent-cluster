"""Configuration constants for the PerfIngest Celery application.

Separate from :mod:`backend.streaming.config` so the ingest workers and
the main streaming workers never share a broker DB or result backend,
preventing key-space collisions.

Redis DB allocation
-------------------
* DB 1: main streaming broker
* DB 2: main streaming backend
* DB 3: perf-ingest broker  (this app)
* DB 4: perf-ingest backend (this app)

Stream keys
-----------
``fin:perf:{thread_id}``
    Per-session token stream.  Ingest workers XADD here; the pub reader
    XREADs from ``0-0`` until it hits the sentinel entry.

``fin:perf:ingest:state:{thread_id}``
    Redis hash tracking ingest progress per session.

``fin:perf:ingest:result:{thread_id}``
    Redis list — ingest worker RPUSH es a JSON completion record here;
    the LangGraph node BLPOP s it to await ingest without polling.

``fin:perf:ingest:active``
    Redis sorted set.  Score = last heartbeat timestamp (Unix seconds).
    Beat recovery uses this to detect stalled sessions and restart them.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Redis DB indices (broker / backend for this Celery app only)
# ---------------------------------------------------------------------------

#: Celery task-dispatch queue for PerfIngest workers.
PERF_INGEST_BROKER_DB: int = 3
#: Celery result backend for PerfIngest tasks.
PERF_INGEST_BACKEND_DB: int = 4

# ---------------------------------------------------------------------------
# Stream / state key prefixes
# ---------------------------------------------------------------------------

#: Per-session token stream: ``fin:perf:{thread_id}``
PERF_INGEST_STREAM_PREFIX: str = "fin:perf"
#: Per-session ingest state hash: ``fin:perf:ingest:state:{thread_id}``
PERF_INGEST_STATE_KEY_PREFIX: str = "fin:perf:ingest:state"
#: Per-session completion signal list: ``fin:perf:ingest:result:{thread_id}``
PERF_INGEST_RESULT_KEY_PREFIX: str = "fin:perf:ingest:result"
#: Sorted set of all active ingest sessions (score = last heartbeat).
PERF_INGEST_ACTIVE_SET_KEY: str = "fin:perf:ingest:active"

# ---------------------------------------------------------------------------
# Ingest behaviour
# ---------------------------------------------------------------------------

#: Tokens written per Celery task invocation (one pipeline flush).
PERF_INGEST_BATCH_SIZE: int = 10_000
#: Soft cap on Redis stream length (XADD MAXLEN ~).
PERF_INGEST_STREAM_MAXLEN: int = 200_000
#: Sentinel field injected at end-of-stream so the pub reader knows to stop.
PERF_INGEST_SENTINEL_FIELD: str = "sentinel"
#: Value of the sentinel field.
PERF_INGEST_SENTINEL_VALUE: str = "1"

# ---------------------------------------------------------------------------
# Beat / recovery
# ---------------------------------------------------------------------------

#: How often (seconds) the beat-recovery task fires.
PERF_INGEST_BEAT_INTERVAL: float = 10.0
#: Seconds without a heartbeat update before a stream is considered stalled.
PERF_INGEST_STALL_THRESHOLD: int = 30
#: Max retries for the bulk-ingest Celery task.
PERF_INGEST_MAX_RETRIES: int = 1
#: Back-off delay (seconds) between retries.
PERF_INGEST_RETRY_DELAY: float = 2.0

# ---------------------------------------------------------------------------
# Pub-side reading
# ---------------------------------------------------------------------------

#: Tokens read per XREAD call in the pub-side stream reader.
PERF_PUB_READ_BATCH_SIZE: int = 1_000

__all__ = [
    "PERF_INGEST_BROKER_DB",
    "PERF_INGEST_BACKEND_DB",
    "PERF_INGEST_STREAM_PREFIX",
    "PERF_INGEST_STATE_KEY_PREFIX",
    "PERF_INGEST_RESULT_KEY_PREFIX",
    "PERF_INGEST_ACTIVE_SET_KEY",
    "PERF_INGEST_BATCH_SIZE",
    "PERF_INGEST_STREAM_MAXLEN",
    "PERF_INGEST_SENTINEL_FIELD",
    "PERF_INGEST_SENTINEL_VALUE",
    "PERF_INGEST_BEAT_INTERVAL",
    "PERF_INGEST_STALL_THRESHOLD",
    "PERF_INGEST_MAX_RETRIES",
    "PERF_INGEST_RETRY_DELAY",
    "PERF_PUB_READ_BATCH_SIZE",
]
