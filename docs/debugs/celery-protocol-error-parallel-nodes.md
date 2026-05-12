# Celery Protocol Error — Parallel Node Result Polling

## Symptom

```
ERROR | [main_thread.executor] graph failed thread_id=...: Protocol Error: b'status": "SUCCESS", "result": {...}'
```

The graph failed immediately after `stats_node` and `news_node` both completed
successfully (Celery tasks returned `SUCCESS`), but the result could not be read.

## Root Cause

`stats_node` and `news_node` run in parallel via `RunnableParallel`.  Each
spawns a LangGraph `@task` that calls `delegate_completion` → `_await_result`.
The original `_await_result` polled the Celery result via:

```python
result = await loop.run_in_executor(
    None,
    lambda t=poll_timeout: async_result.get(timeout=t),
)
```

Two concurrent `run_in_executor` threads both called `async_result.get()` on
different `AsyncResult` objects but sharing the **same synchronous Celery
result backend** (`celery_engine.backend`), which uses one `redis.ConnectionPool`.

When two threads read from the same TCP socket simultaneously, they split the
response:

- Thread A reads the RESP prefix `$<N>\r\n{"` (bulk-string header + first 2 bytes)
- Thread B reads the remainder: `status": "SUCCESS", ...}`
- Thread B encounters `s` (from `status`) as the first byte of what it expects to
  be a fresh RESP response → `hiredis` raises `ProtocolError`
- `redis-py` re-raises as `InvalidResponse: Protocol Error: b'status": ...'`

The missing `{"` confirmed two bytes had already been consumed by the other thread.

## Fix

Replaced `run_in_executor(async_result.get)` with direct **async Redis polling**
of `celery-task-meta-{celery_task_id}` using a dedicated `redis.asyncio` client
(DB 2, shard 0).  This runs entirely on the asyncio event loop — no thread pool,
no shared synchronous connection pool.

Key changes in `backend/celery_task/workers/task_delegation.py`:

- Added `_get_result_backend_client()` which lazily creates a `redis.asyncio.Redis`
  client for the Celery result backend URL (shard 0, DB `CELERY_BACKEND_DB = 2`).
- `_await_result` now does `await client.get(result_key)` and parses the JSON
  directly instead of delegating to `AsyncResult.get()` in a thread.
- Removed `import celery.exceptions` (no longer needed in the hot path).
- `revoke_celery_task` (cancel/timeout path) still works — it uses the
  `AsyncResult` stored in the registry to send a revoke command synchronously.

## Verification

Trigger a new thread that runs `stats_node` + `news_node` in parallel.  The
graph should complete without `Protocol Error`.  Check `logs/graph.log` for
`[lifecycle:node] completed` entries for both nodes.
