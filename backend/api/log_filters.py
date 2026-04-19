"""Logging filters for the FastAPI / HTTP access layer.

Provides :class:`HealthCheckThrottleFilter` which throttles the repetitive
uvicorn access-log records for health-check and documentation endpoints
(``/docs``, ``/health``, ``/openapi.json``, ``/redoc``, ``/favicon.ico``)
to a 2-minute summary line on the console handler.
"""

from __future__ import annotations

import logging
import threading
import time

__all__ = ["HealthCheckThrottleFilter"]


class HealthCheckThrottleFilter(logging.Filter):
    """Throttle repetitive health-check endpoint access log records.

    Paths like ``/docs``, ``/health``, ``/openapi.json``, and ``/redoc``
    are polled frequently by load balancers and browsers.  Each matching
    record is dropped and its count accumulated.  Every 5 minutes the
    first suppressed record is replaced with a summary line.
    """

    _INTERVAL: float = 300.0  # 5 minutes
    _THROTTLED: frozenset[str] = frozenset(
        {"/docs", "/health", "/openapi.json", "/redoc", "/favicon.ico"}
    )

    def __init__(self) -> None:
        """Initialise counters and the interval clock."""
        super().__init__()
        self._counts: dict[str, int] = {}
        self._last_flush: float = time.monotonic()
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        """Suppress or summarise health-check access records.

        Args:
            record: The uvicorn access log record to evaluate.

        Returns:
            ``True`` to pass the record through, ``False`` to drop it.
        """
        # uvicorn access records expose `request_line` as an extra attribute
        # e.g. "GET /docs HTTP/1.1"
        request_line: str = getattr(record, "request_line", "") or ""
        if not request_line:
            # Fallback: scan the composed message
            request_line = record.getMessage()

        parts = request_line.split()
        path = parts[1] if len(parts) >= 2 else ""

        if path not in self._THROTTLED:
            return True

        with self._lock:
            self._counts[path] = self._counts.get(path, 0) + 1
            now = time.monotonic()
            if now - self._last_flush >= self._INTERVAL:
                self._last_flush = now
                snapshot = dict(self._counts)
                self._counts.clear()
                summary = ", ".join(
                    f"{p}: {c}x" for p, c in sorted(snapshot.items())
                )
                record.msg = f"[Health endpoints 2-min summary] {summary}"
                record.args = None
                record.__dict__.update(
                    request_line="[summary]", client_addr="-", status_code="-"
                )
                return True
            return False
