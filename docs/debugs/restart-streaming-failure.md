# Restart Streaming Failure

## Symptoms

1. After backend restart, a recovered thread showed no LLM token output in the
   frontend despite:
   - `GET /api/v1/auth/centrifugo/llm-token?thread_id=... HTTP/1.1" 200 OK` —
     frontend successfully connected to centrifugo-llm.
   - `WARNING [task_delegation] waiting for celery task_id=18ff634e-... thread_id=b074fc82-... elapsed_s=30` —
     stream Celery task stuck PENDING for 30 + seconds.

## Root Cause 1 — Multi-instance `control.purge()` race (HIGH)

### What happened

`RUNNER_INSTANCE_COUNT > 1` means multiple FastAPI processes start concurrently
and each runs the full `lifespan` sequence:

```
cleanup_stale_celery_tasks()   # calls control.purge()
recover_running_threads()      # dispatches stream tasks
```

Race:

1. **Instance A** runs cleanup (revoke + purge) → then recovers thread → dispatches
   stream task to the Celery queue.
2. **Instance B** starts slightly later → runs cleanup → calls `control.purge()` →
   **purges Instance A's newly-dispatched stream task**.
3. `_await_result` in `task_delegation.py` polls `celery-task-meta-{id}` on Redis
   DB 2 every 0.5 s.  Since no worker ever picked up the purged task, the meta key
   is never written → task stays PENDING indefinitely → 30-second warning fires.

### Fix

Added a Redis distributed lock (`fin:startup:celery:purge`, 60 s TTL, SET NX) in
`cleanup_stale_celery_tasks()`.  The first instance to acquire it runs
`control.purge()`; all subsequent instances within the same restart cycle skip the
purge.  All instances still independently revoke their own stale active tasks
(revoke is safe to call redundantly).

File: `backend/main_thread/startup.py` → `cleanup_stale_celery_tasks()`

## Root Cause 2 — Missing viewer-flag refresh on recovery (MEDIUM)

### What happened

When a query is submitted, `submit_query` sets:

- `fin:user:app_viewer:{user_id}` (30 min TTL, Redis shard 0)
- `fin:thread:viewer:{thread_id}` (30 min TTL, Redis shard 0)

These flags control token publishing in `stream_core.py`:

```python
viewers_present = (
    await has_app_viewers(thread_id)    # checks fin:user:app_viewer:{user_id}
    and await has_thread_viewers(thread_id)  # checks fin:thread:viewer:{thread_id}
)
# ...
if viewers_present:
    await stream_token_batch(thread_id, batch)  # only then publish tokens
```

The `recover_running_threads()` startup helper did **not** call `set_viewer()`
before dispatching recovery.  If the flags had expired (>30 min since original
submission) or been cleared by the frontend's `clearThreadViewer()` call (browser
refresh/close), `viewers_present` evaluated to `False` and all tokens were silently
discarded — the LLM ran to completion but nothing reached the Redis stream.

The 200 OK on the LLM token endpoint confirmed the frontend subscribed
successfully, but there was simply nothing published to the channel.

### Fix

Updated `recover_running_threads()` to include `user_id` in the recovery SQL
query and call `set_thread_user()` + `set_viewer()` before `dispatch_graph_run()`,
mirroring exactly what `submit_query` does for new queries.

File: `backend/main_thread/startup.py` → `recover_running_threads()`

## Full call chain (restart scenario)

```
backend restart
  └─ cleanup_stale_celery_tasks()
       ├─ inspect().active() → revoke old tasks (terminate=True)
       └─ Redis SET NX fin:startup:celery:purge
            ├─ acquired → control.purge()       (only first instance)
            └─ not acquired → skip purge        (all other instances)
  └─ recover_running_threads()
       ├─ SQL: SELECT thread_id, query, user_id FROM user_queries WHERE running...
       └─ for each thread:
            ├─ check lock ownership (skip if another live instance owns it)
            ├─ set_thread_user(thread_id, user_id)   ← NEW
            ├─ set_viewer(user_id, thread_id)        ← NEW
            └─ dispatch_graph_run(thread_id, query, resume=True)
```

## Related docs

- `docs/debugs/concurrency-grid-zero-tokens-stuck-running.md` — similar viewer
  flag race at query submission time (set_viewer called after dispatch, now fixed
  to call before dispatch).  The recovery path had the same bug until this fix.
