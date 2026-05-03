"""Shared in-memory LRU cache with per-entry TTL for API response memoization.

Provides a lightweight L1 cache layer in front of the DB-backed (L2) caches
in ``quant_api.client`` and ``news_api.client``.

Cache hierarchy:
  L1 (this module)  — in-memory, 1-hour TTL, max 512 entries, process-local
  L2 (DB)           — ``fin_markets.quant_raw`` / ``news_raw``, 4-hour TTL
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Optional

_DEFAULT_TTL: float = 3600.0   # 1 hour
_DEFAULT_MAX_SIZE: int = 512


class TimedLRUCache:
    """OrderedDict-backed LRU cache with a per-entry TTL.

    Entries are evicted lazily on ``get`` when they exceed ``ttl_seconds``.
    When ``max_size`` is reached the least-recently-used entry is evicted.

    Not thread-safe for concurrent writes — suitable for use within a single
    asyncio event loop where co-routines execute cooperatively.
    """

    def __init__(
        self,
        max_size: int = _DEFAULT_MAX_SIZE,
        ttl_seconds: float = _DEFAULT_TTL,
    ) -> None:
        """Initialise with capacity and time-to-live.

        Args:
            max_size:    Maximum number of entries before LRU eviction.
            ttl_seconds: Seconds an entry remains valid (default 3600 = 1 hr).
        """
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for *key*, or ``None`` if absent or expired.

        An expired entry is automatically removed on retrieval.
        """
        entry = self._store.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key*, evicting the LRU entry when at capacity."""
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic(), value)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def evict_expired(self) -> int:
        """Remove all entries older than ``ttl_seconds`` eagerly.

        Returns:
            The number of entries removed.
        """
        now = time.monotonic()
        expired = [k for k, (ts, _) in list(self._store.items()) if now - ts > self._ttl]
        for k in expired:
            del self._store[k]
        return len(expired)

    def clear(self) -> None:
        """Remove all entries unconditionally."""
        self._store.clear()

    def __len__(self) -> int:
        """Return the number of entries currently stored (including stale)."""
        return len(self._store)
