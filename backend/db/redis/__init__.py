"""backend.db.redis — lazy async Redis clients, one per shard.

Initialisation is deferred to first access so there is no event-loop
dependency at import time.  Clients are keyed by shard index and reused
for the lifetime of the process.

Usage::

    from backend.db.redis import get_client, shard_for_thread

    redis = await get_client(shard_for_thread(thread_id))
    await redis.xadd("fin:llm:tokens:0", {"thread_id": tid, "token": t})

Implementation split
--------------------
client.py — client pool, shard mapping, get_client, close_all
"""

from backend.db.redis.client import close_all, get_client, shard_for_thread

__all__ = ["get_client", "close_all", "shard_for_thread"]
