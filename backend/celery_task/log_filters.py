"""Logging filters for the Celery / streaming layer.

Provides :class:`CeleryTaskSummaryFilter` which suppresses the per-invocation
"Task … received / succeeded" and "Scheduler: Sending due task" noise and
replaces it with a 5-minute summary line on the console handler.
"""

from __future__ import annotations

import logging
import re
import threading
import time

__all__ = ["CeleryTaskSummaryFilter"]

_CELERY_TASK_PAT = re.compile(
    r"Task (\S+)\[|Sending due task \S+ \((\S+)\)|missed heartbeat from (\S+)"
)

# Pattern for standalone "missed heartbeat" lines that don't match the task
# pattern above (some Celery versions emit them differently).
_HEARTBEAT_PAT = re.compile(r"missed heartbeat from")


class CeleryTaskSummaryFilter(logging.Filter):
    """Suppress per-invocation Celery task/scheduler logs.

    Individual "Task X received", "Task X succeeded", and
    "Scheduler: Sending due task" records are silenced on the console.
    Every 5 minutes the first suppressed record in that window is replaced
    with a plain-text summary of cumulative invocation counts so the console
    stays quiet but auditable.
    """

    _INTERVAL: float = 300.0  # 5 minutes

    def __init__(self) -> None:
        """Initialise counters and the interval clock."""
        super().__init__()
        self._counts: dict[str, int] = {}
        self._last_flush: float = time.monotonic()
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        """Suppress or summarise Celery lifecycle records.

        Args:
            record: The log record to evaluate.

        Returns:
            ``True`` to pass the record through, ``False`` to drop it.
        """
        msg = record.getMessage()
        m = _CELERY_TASK_PAT.search(msg)
        if m is None:
            # Also suppress bare "missed heartbeat" lines not captured by the
            # main pattern (observed on some Celery versions).
            if _HEARTBEAT_PAT.search(msg):
                task_name = "missed-heartbeat"
            else:
                return True  # unrelated message — always pass
        else:
            task_name = m.group(1) or m.group(2) or m.group(3) or "unknown"
        with self._lock:
            self._counts[task_name] = self._counts.get(task_name, 0) + 1
            now = time.monotonic()
            if now - self._last_flush >= self._INTERVAL:
                self._last_flush = now
                snapshot = dict(self._counts)
                self._counts.clear()
                lines = [f"[Celery {self._INTERVAL/60:.0f}-min summary]"] + [
                    f"  {t}: {c} invocations"
                    for t, c in sorted(snapshot.items())
                ]
                record.msg = "\n".join(lines)
                record.args = None
                return True
            return False
