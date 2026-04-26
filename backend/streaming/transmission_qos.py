"""Transmission Quality-of-Service — first-token latency monitor and flush accelerator.

Audits active perf-test streams every :data:`_AUDIT_INTERVAL` seconds.  Any
stream that has been registered for at least :data:`_STALL_THRESHOLD_SECS`
without emitting its first token batch is considered stalled; its
flush-request event is set so that :func:`~backend.sse_notifications.agent_tasks.token_stream.stream_perf_text_task`
emits whatever partial batch it has accumulated immediately rather than waiting
for the full ``_PERF_BATCH_SIZE``.

Architecture
------------
The :data:`transmission_qos` singleton is created at module import time.  The
FastAPI lifespan startup calls :meth:`TransmissionQoS.start` to spawn the
background audit coroutine in the event loop; the shutdown path calls
:meth:`TransmissionQoS.stop`.

``stream_perf_text_task`` interacts with the registry via:

* :meth:`TransmissionQoS.register` — called on stream open; returns an
  :class:`asyncio.Event` the task polls to detect flush requests.
* :meth:`TransmissionQoS.mark_first_token` — called once the first batch
  is emitted so the auditor stops flagging the stream.
* :meth:`TransmissionQoS.unregister` — called on stream close (always in
  a ``finally`` block).

Thread-safety
-------------
All public methods are called exclusively from the FastAPI asyncio event loop
(the same loop that runs the audit coroutine), so no locks are needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from backend.streaming.errors import STREAM_QOS_STALL

logger = logging.getLogger(__name__)

#: Seconds between QoS audit sweeps.
_AUDIT_INTERVAL: float = 3.0

#: A stream idle this many seconds without a first token is considered stalled.
_STALL_THRESHOLD_SECS: float = 3.0


@dataclass
class _StreamEntry:
    """Per-stream tracking state.

    Attributes:
        started_at:     Monotonic timestamp when the stream was registered.
        first_token_at: Monotonic timestamp when the first batch was emitted,
                        or ``None`` if no batch has been emitted yet.
        flush_event:    :class:`asyncio.Event` set by the auditor to request
                        an early partial flush of the accumulation buffer.
    """

    started_at: float = field(default_factory=time.monotonic)
    first_token_at: float | None = None
    flush_event: asyncio.Event = field(default_factory=asyncio.Event)


class TransmissionQoS:
    """Registry that tracks active perf-test streams and audits for first-token stalls.

    Usage pattern::

        # At stream open:
        flush_event = transmission_qos.register(thread_id)

        # Inside token accumulation loop:
        if batch_count >= BATCH_SIZE or flush_event.is_set():
            emit_batch(...)
            flush_event.clear()
            transmission_qos.mark_first_token(thread_id)

        # At stream close (always in finally):
        transmission_qos.unregister(thread_id)
    """

    def __init__(self) -> None:
        self._streams: dict[str, _StreamEntry] = {}
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Registration helpers (called from stream_perf_text_task)
    # ------------------------------------------------------------------

    def register(self, thread_id: str) -> asyncio.Event:
        """Register *thread_id* as an active stream and return its flush event.

        The returned :class:`asyncio.Event` is polled by ``stream_perf_text_task``
        inside the token-accumulation loop.  When the auditor detects a stall it
        sets the event; the task then flushes whatever partial batch it has
        buffered immediately.

        Args:
            thread_id: LangGraph thread UUID.

        Returns:
            The flush-request :class:`asyncio.Event` for this stream.
        """
        entry = _StreamEntry()
        self._streams[thread_id] = entry
        logger.debug("[transmission_qos] registered thread_id=%s", thread_id)
        return entry.flush_event

    def mark_first_token(self, thread_id: str) -> None:
        """Record that the first token batch has been emitted for *thread_id*.

        After this call the auditor will no longer flag this stream as stalled
        and ``first_token_latency`` is logged for observability.

        Args:
            thread_id: LangGraph thread UUID.
        """
        entry = self._streams.get(thread_id)
        if entry is not None and entry.first_token_at is None:
            entry.first_token_at = time.monotonic()
            latency = entry.first_token_at - entry.started_at
            logger.info(
                "[transmission_qos] first_token_emitted latency=%.3fs thread_id=%s",
                latency,
                thread_id,
            )

    def unregister(self, thread_id: str) -> None:
        """Remove *thread_id* from the registry after the stream closes.

        Always call this from a ``finally`` block to avoid memory leaks.

        Args:
            thread_id: LangGraph thread UUID.
        """
        self._streams.pop(thread_id, None)
        logger.debug("[transmission_qos] unregistered thread_id=%s", thread_id)

    @property
    def active_count(self) -> int:
        """Return the number of currently registered streams."""
        return len(self._streams)

    # ------------------------------------------------------------------
    # Audit loop (started / stopped by FastAPI lifespan)
    # ------------------------------------------------------------------

    async def _audit_loop(self) -> None:
        """Background coroutine — sweep every :data:`_AUDIT_INTERVAL` seconds.

        Finds streams that have been running for ≥ :data:`_STALL_THRESHOLD_SECS`
        without emitting a first token and sets their ``flush_event`` so the
        reading task flushes its partial buffer immediately rather than waiting
        for the full batch threshold.
        """
        while True:
            await asyncio.sleep(_AUDIT_INTERVAL)
            now = time.monotonic()
            stalled: list[str] = []
            for thread_id, entry in list(self._streams.items()):
                if (
                    entry.first_token_at is None
                    and now - entry.started_at >= _STALL_THRESHOLD_SECS
                    and not entry.flush_event.is_set()
                ):
                    entry.flush_event.set()
                    stalled.append(thread_id)

            if stalled:
                logger.warning(
                    "[%s] stall_detected count=%d active=%d "
                    "sample_thread_ids=%s",
                    STREAM_QOS_STALL,
                    len(stalled),
                    len(self._streams),
                    stalled[:5],
                )

    def start(self) -> None:
        """Spawn the audit coroutine in the running asyncio event loop.

        Safe to call multiple times — only one audit task runs at a time.
        Must be called after the event loop is running (i.e. inside a FastAPI
        lifespan or ``@app.on_event("startup")`` handler).
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._audit_loop(), name="transmission-qos-audit"
            )
            logger.info(
                "[transmission_qos] audit loop started interval=%.0fs threshold=%.0fs",
                _AUDIT_INTERVAL,
                _STALL_THRESHOLD_SECS,
            )

    def stop(self) -> None:
        """Cancel the audit coroutine on application shutdown."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None
            logger.info("[transmission_qos] audit loop stopped")


#: Module-level singleton — shared across all streams in the FastAPI event loop.
transmission_qos: TransmissionQoS = TransmissionQoS()

__all__ = ["TransmissionQoS", "transmission_qos"]
