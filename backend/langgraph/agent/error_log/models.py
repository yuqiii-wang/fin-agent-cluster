"""Pydantic model for a deduplicated per-thread error/warning log entry."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ThreadLogEntry(BaseModel):
    """One deduplicated WARNING+ log entry captured for a thread.

    Many raw log records collapse into a single entry: records that share a
    normalized signature (same logger/level with dynamic numbers and whitespace
    stripped) increment ``count`` instead of stacking, which prevents duplicate
    and repeated stack-trace noise from flooding the recovery context.

    Attributes:
        level:    Log level name (``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``).
        logger:   Logger name that emitted the record.
        message:  Cleaned, single-line message (no full traceback), truncated
                  to the configured per-entry character cap.
        count:    Number of raw records collapsed into this entry.
        last_ts:  ISO-8601 timestamp (UTC) of the most recent occurrence.
    """

    level: str
    logger: str
    message: str
    count: int
    last_ts: datetime

    model_config = {"frozen": True}


__all__ = ["ThreadLogEntry"]
