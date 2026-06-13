"""Non-blocking logging handler that captures WARNING+ records per thread.

Pipeline
--------
1. :class:`ThreadErrorLogHandler.emit` runs synchronously at the log call site.
   It is intentionally cheap: it reads the bound ``thread_id`` (skipping records
   with none), cleans the record to a single traceback-free line, computes a
   dedup signature, and ``put_nowait`` s a small dict onto a bounded in-process
   queue.  It never blocks and never raises into the caller.
2. A single background daemon thread runs its own asyncio loop, drains the queue,
   and upserts each item into the Redis-backed per-thread store
   (:mod:`.store`).  Heavy work (Redis I/O, deduplication) happens here, off the
   hot path and out of the event loop running the graph.

Lifecycle
---------
``start_listener`` is idempotent and is called by ``configure_logging`` after
``dictConfig`` installs the handler.  ``stop_listener`` (registered via
``atexit``) drains and shuts the thread down cleanly.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import queue
import threading

from backend.config import get_settings
from backend.langgraph.agent.error_log.context import get_log_thread_id
from backend.langgraph.agent.error_log.signature import clean_message, make_signature
from backend.langgraph.agent.error_log.store import record_thread_log

# Bounded queue of captured records awaiting the background Redis write.
_queue: queue.Queue[dict | None] = queue.Queue(maxsize=get_settings().AGENT_ERRLOG_QUEUE_MAX)

# Background writer thread + the PID it was started under.  Tracking the PID
# makes start-up safe across ``fork`` (Celery prefork): a forked child inherits
# the parent's (dead) Thread object, so we restart the writer when the running
# PID no longer matches.
_listener_thread: threading.Thread | None = None
_listener_pid: int | None = None
_listener_lock = threading.Lock()
_stop = threading.Event()

# Re-entrancy guard so a log emitted by the handler's own write path (or the
# Redis client) can never recurse back into capture on the same thread.
_local = threading.local()


class ThreadErrorLogHandler(logging.Handler):
    """Capture WARNING+ records tagged with the current thread_id.

    Attached (via ``log_config``) to the application loggers whose WARNING+
    output is useful for agent failure recovery.  Records without a bound
    thread_id, or below WARNING, are ignored.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Enqueue a cleaned, deduplicated form of *record* for background write.

        Args:
            record: The log record being emitted.
        """
        if record.levelno < logging.WARNING:
            return
        if getattr(_local, "in_capture", False):
            return
        thread_id = get_log_thread_id()
        if not thread_id:
            return

        try:
            _local.in_capture = True
            _ensure_listener()
            char_cap = get_settings().AGENT_ERRLOG_CHAR_CAP
            message = clean_message(record, char_cap=char_cap)
            item = {
                "thread_id": thread_id,
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                "signature": make_signature(record.name, record.levelname, message),
            }
            _queue.put_nowait(item)
        except queue.Full:
            pass
        except Exception:  # noqa: BLE001 -- logging must never raise
            pass
        finally:
            _local.in_capture = False


async def _drain_loop() -> None:
    """Drain the capture queue into the per-thread Redis store until stopped."""
    while True:
        try:
            item = _queue.get(timeout=0.5)
        except queue.Empty:
            if _stop.is_set():
                return
            continue
        if item is None:  # shutdown sentinel
            return
        try:
            await record_thread_log(
                item["thread_id"],
                signature=item["signature"],
                level=item["level"],
                logger_name=item["logger"],
                message=item["message"],
            )
        except Exception:  # noqa: BLE001
            pass


def _run_listener() -> None:
    """Entry point for the background writer thread (owns its own event loop)."""
    asyncio.run(_drain_loop())


def start_listener() -> None:
    """Start the background writer thread for this process (idempotent).

    Restarts the thread when the running PID differs from the one that last
    started it, so each ``fork``-ed Celery worker child gets its own writer.
    """
    global _listener_thread, _listener_pid
    pid = os.getpid()
    with _listener_lock:
        if (
            _listener_thread is not None
            and _listener_pid == pid
            and _listener_thread.is_alive()
        ):
            return
        _stop.clear()
        _listener_thread = threading.Thread(
            target=_run_listener, name="thread-errlog-writer", daemon=True
        )
        _listener_pid = pid
        _listener_thread.start()
        atexit.register(stop_listener)


def _ensure_listener() -> None:
    """Start the writer thread if none is running for the current process."""
    if _listener_pid == os.getpid() and _listener_thread is not None and _listener_thread.is_alive():
        return
    start_listener()


def stop_listener() -> None:
    """Signal the writer thread to drain and exit (best-effort)."""
    _stop.set()
    try:
        _queue.put_nowait(None)
    except queue.Full:
        pass


__all__ = ["ThreadErrorLogHandler", "start_listener", "stop_listener"]
