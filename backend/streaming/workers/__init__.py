"""Celery streaming workers — LLM ingest, throughput, fanout, and PG persistence.

Workers by test mode
--------------------
throughput   — ``run_stream_ingest_throughput``: bulk-writes all tokens as fast as possible;
               token-bounded completion; dispatcher awaits result via ``async_result.get()``.
fanout       — ``run_fanout_batch``: runs ALL streams in a ``run_id`` batch concurrently
               via ``asyncio.gather()``; sharded into tasks of ``MAX_STREAMS_PER_FANOUT_TASK``
               by the coordinator for high-concurrency support.

Shared workers
--------------
llm_ingest   — Streams LLM tokens to ``fin:llm:tokens`` (Centrifugo native consumer).
pg_persist   — Beat task: persists ``fin:llm:completions`` records to PostgreSQL.
"""

__all__ = ["llm_ingest", "throughput", "fanout", "pg_persist"]
