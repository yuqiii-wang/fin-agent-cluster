# E2E Flow Guide — fin-trading-cluster

This skill describes the end-to-end request/response and streaming pipeline.
Reference it whenever adding new features, debugging SSE delivery, or tracing lifecycle events.

---

## Architecture Overview

Two distinct flows exist. **Never mix them** in the same feature:

| Flow | Transport | Use case |
|------|-----------|----------|
| **Streaming** | Redis Streams (tokens) + Redis Pub/Sub (lifecycle) | LLM token delivery, perf-test |
| **Non-streaming** | REST request/response or SSE lifecycle events | Query submission, status, control |

All events that reach the browser originate from the FastAPI main process (`backend/api/`).
Celery workers handle **only** Redis Stream batch consumers — they never emit SSE events.

---

## Request Lifecycle — Both Branches

### 1. Query Submission (POST /api/v1/users/query)

```
Client → POST /users/query {query, perf_params}
  └─ backend/api/queries.py
       ├─ Dedup guard (SELECT … WHERE status IN ('received','pending','running') AND created_at > -60s)
       ├─ INSERT user_queries (status='received', extra.perf_params)
       ├─ set_query_phase(thread_id, "received")      → Redis key query_phase:{thread_id}
       ├─ emit_query_status(thread_id, "received")    → publish_lifecycle → Redis Pub/Sub
       ├─ emit_query_received(thread_id)              → publish_lifecycle + push_pending_notify
       └─ return {thread_id, status='received'}
```

The graph is **not started** at this point. The client must ACK.

### 2. SSE Subscribe (GET /api/v1/stream/{thread_id})

```
Client → GET /stream/{thread_id}
  └─ backend/api/stream.py  _event_gen()
       ├─ yield connected event
       ├─ replay_existing(thread_id)        → DB query for current status + all agent_tasks
       │    └─ injects query_status phase from Redis if status in (running, received)
       │    └─ injects query_received if status == received
       │    └─ yields started/completed/failed for each existing task row
       ├─ if already terminal → yield done → return
       ├─ if query_status != 'received' and NOT is_task_active_any_instance(thread_id):
       │    └─ handle_orphaned_query()  ← RACE GUARD: re-reads DB before UPDATE to avoid
       │         overwriting a just-completed query (runner finished between replay and here)
       │    └─ yield done → return
       ├─ open read_lifecycle(thread_id) → Redis Pub/Sub lifecycle:<thread_id>
       ├─ open read_stream(thread_id)    → Redis Streams XREAD tokens:<thread_id>
       ├─ post-subscribe re-check: replay_existing() again if no prior replay events
       └─ dual-source fan-in loop:
            merged_queue ← _pump_lifecycle + _pump_tokens
            25s timeout → ping + drain_pending_notify recovery
            token events → watch-registry filter (only forwarded if task_id matches watched task)
            perf_token_batch → always forwarded (bypass watch filter)
            done event → two asyncio.sleep(0) drain + remaining perf_token_batch flush
```

**Post-subscribe race window fix**: The `replay_existing()` call after LISTEN subscription
closes the window where `create_task` committed and fired pg_notify while `replay_existing`
was running (before LISTEN was active).

### 3. Client ACK (POST /api/v1/users/query/{thread_id}/ack)

```
Client → POST /users/query/{thread_id}/ack
  └─ backend/api/queries.py  ack_query()
       ├─ SELECT … FOR UPDATE (row-level lock prevents duplicate ACKs)
       ├─ if already running & acked → re-emit query_ack_confirmed (idempotent)
       ├─ UPDATE user_queries status='running', is_ack=True
       ├─ ack_pending_notify(thread_id, 'query_received')  → mark drain cycle complete
       ├─ asyncio.create_task(run_graph_async(...))         → FastAPI event loop
       ├─ running_tasks[thread_id] = task
       ├─ mark_task_active(thread_id)  → Redis key task_active:{thread_id} (TTL 1h)
       ├─ emit_query_ack_confirmed(thread_id)  → publish_lifecycle → Redis Pub/Sub → SSE
```

---

## Graph Execution — run_graph_async()

`backend/graph/runner.py` is the unified execution entrypoint.

```
asyncio.create_task(run_graph_async(thread_id, query, perf_params))
  └─ set_query_phase("preparing") + emit_query_status("preparing")
  └─ graph.ainvoke(initial_state, config)
       ├─ Fin-analysis branch: query_optimizer → market_data_collector → decision_maker
       └─ Perf-test branch:    perf_test_streamer
  └─ _running_tasks.pop(thread_id)   ← synchronous before any await
  └─ UPDATE user_queries SET status='completed' WHERE status='running' RETURNING thread_id
  └─ if claimed: emit_done(thread_id, 'completed', report)
  └─ cleanup_thread_session(thread_id)   ← clears task_active Redis key
```

**Ownership claim**: only one writer (runner or cancel endpoint) can claim the `done`
transition by atomically updating `WHERE status='running'`. Whoever gets 0 rows is the loser.

---

## Event Delivery — Two Channels

### Channel A: Redis Streams — token events

```
LangGraph node
  └─ stream_text_task / stream_llm_task / stream_perf_text_task
       └─ stream_token(thread_id, {event, task_id, data})
            └─ XADD tokens:{thread_id}  (MAXLEN ~ 10 000)
                 └─ read_stream() XREAD BLOCK 2000ms in SSE generator
                      └─ _pump_tokens → merged_queue → SSE generator → browser
```

Events delivered via Redis Streams: `token`, `perf_token_batch`, `perf_concurrent_status`.

**`stream_perf_text_task` batching**: tokens accumulated exponentially (1 → 2 → 4 → … → 1024)
then flushed as a single `perf_token_batch` event. `TransmissionQoS` auditor force-flushes
any stalled stream after 3s so the browser sees its first event quickly.

### Channel B: Redis Pub/Sub — lifecycle events

```
publish_lifecycle(thread_id, {event, ...})   ← called AFTER session.commit()
  └─ PUBLISH lifecycle:{thread_id} json      ← direct, shard-routed via RedisRouter
       └─ read_lifecycle() Pub/Sub subscribe in SSE generator
            └─ _pump_lifecycle → merged_queue → SSE generator → browser
```

Events delivered via lifecycle channel: `started`, `completed`, `failed`, `cancelled`, `done`,
`query_received`, `query_ack_confirmed`, `query_status`,
`perf_ingest_progress`, `perf_ingest_complete`, `perf_test_stopped`, `perf_test_complete`.

**Ordering guarantee**: `publish_lifecycle` is always called after `session.commit()` so the
DB row is durable before any subscriber reads it.  No PG NOTIFY/LISTEN or fanout task is
involved — lifecycle events go directly from the FastAPI process to Redis Pub/Sub.

**`pg_notify_in_session` vs `pg_notify`** — these functions have been removed.
All lifecycle notification now uses `publish_lifecycle(thread_id, payload)` from
`backend.sse_notifications.channel`.

---

## Fin-Analysis Pipeline (Regular Queries)

```
query_optimizer node
  └─ create_task(thread_id, "query_optimizer.extract")  → DB INSERT + pg_notify "started"
  └─ stream_text_task(...)                              → XADD tokens:{thread_id}
  └─ complete_task(thread_id, task_id, ...)             → DB UPDATE + pg_notify "completed"

market_data_collector node
  └─ create_task(...) / complete_task(...) per sub-task (ohlcv, volume, etc.)
  └─ stream_text_task(...)  for each LLM sub-task

decision_maker node
  └─ create_task(thread_id, "decision_maker.llm_infer")
  └─ stream_text_task(...)   → individual `token` events per LLM chunk
  └─ complete_task(...)
  └─ create_task(thread_id, "decision_maker.db_insert")
  └─ complete_task(...)
```

SSE filter: `token` events are only forwarded when `task_id == watched_task_id`
(watch registered via `PUT /stream/{thread_id}/watch`). This prevents flooding the
browser with tokens from background tasks the user hasn't opened.

---

## Perf-Test Pipeline

### Throughput Mode

```
perf_test_streamer node
  ├─ set_query_phase("ingesting") + emit_query_status("ingesting")
  ├─ create_task(thread_id, PERF_TEST_INGEST)
  │
  ├─ Phase 1: run_ingest_first_half()
  │    └─ XADD fin:perf:{thread_id} × 95% of total_tokens (async pipeline)
  │    └─ emit_perf_ingest_progress(...)  every 1s  → pg_notify → lifecycle SSE
  │
  ├─ complete_task(thread_id, PERF_TEST_INGEST, {produced, stop_reason})  → pg_notify "completed"
  ├─ emit_perf_ingest_complete(thread_id, ingest_ms, produced, stop_reason)  → pg_notify
  │
  ├─ set_query_phase("digesting") + emit_query_status("digesting")
  ├─ create_task(thread_id, PERF_TEST_PUB)
  │
  └─ Phase 2: asyncio.gather(
       run_ingest_second_half()          → XADD remaining 5% + sentinel
       stream_perf_text_task(
         dynamic_reader_gen()            → XREAD fin:perf:{thread_id} adaptive batch
       )                                 → XADD perf_token_batch to tokens:{thread_id}
     )
  ├─ complete_task(thread_id, PERF_TEST_PUB, {published, tps})
  ├─ emit_perf_test_complete() or emit_perf_test_stopped()  → pg_notify
  └─ (runner) emit_done(thread_id, 'completed')             → pg_notify
```

### Concurrency Mode

```
perf_test_streamer node
  ├─ set_query_phase("digesting") + emit_query_status("digesting")
  ├─ create_task(thread_id, PERF_TEST_PUB)
  ├─ register_concurrency_ingest(thread_id, progress)
  │
  └─ asyncio.gather(
       run_rate_limited_ingest()   → rate-limited XADD at token_per_sec
                                    → emit_perf_ingest_progress every 1s
                                    → checks progress.stable flag (from frontend stable-signal)
       stream_perf_text_task(
         dynamic_reader_gen()      → XREAD fin:perf:{thread_id} adaptive batch
                                    → emit perf_concurrent_status every window via stream_token
       )
     )
  ├─ unregister_concurrency_ingest(thread_id)
  ├─ complete_task(thread_id, PERF_TEST_PUB)
  ├─ emit_perf_test_complete() (stable) or emit_perf_test_stopped() (timeout)
  └─ (runner) emit_done()
```

**Multiple concurrent streams**: each session gets its own `thread_id`, isolated Redis Stream,
Pub/Sub channel, and `asyncio.Task`. `_active_ingest` and `TransmissionQoS._streams` are
keyed by `thread_id` — no cross-session interference.

---

## Key Redis Keys (all routed per thread_id hash to consistent shard)

| Key pattern | Type | Set by | Read by |
|-------------|------|--------|---------|
| `tokens:{thread_id}` | Stream | `stream_token()` XADD | SSE `read_stream()` XREAD |
| `fin:perf:{thread_id}` | Stream | ingest tasks | `dynamic_reader_gen()` XREAD |
| `lifecycle:{thread_id}` | Pub/Sub channel | `lifecycle_fanout` PUBLISH | SSE `read_lifecycle()` SUBSCRIBE |
| `task_active:{thread_id}` | String (TTL 1h) | `mark_task_active()` | `is_task_active_any_instance()` |
| `query_phase:{thread_id}` | String | `set_query_phase()` | `get_query_phase()` in replay |
| `watch:{thread_id}` | String | `register_watch()` | SSE token filter |
| `pending_notify:{thread_id}:*` | Hash | `push_pending_notify()` | `drain_pending_notify()` 25s timeout |
| `lock:lifecycle_fanout` | String (TTL 300s) | `RedisLock` leader | leader election |

---

## Known Race Windows and Their Fixes

### Race 1: started event before SSE client subscribes
**Window**: `create_task()` commits and fires pg_notify before client opens `read_lifecycle()`.
**Fix**: `post-subscribe re-check` — after opening both channels, **always** call
`replay_existing()` again and emit any tasks NOT already in `replayed_task_ids` (the set
collected during initial replay).  Previously this was guarded by `if not replay_events`,
which meant a task created in the race window during an active reconnect was silently dropped.

### Race 2: done event arrives before last perf_token_batch events
**Window**: pg_notify `done` arrives via Pub/Sub faster than the last Redis Stream XREAD cycle.
**Fix**: `stream.py` two `asyncio.sleep(0)` after receiving `done` drains remaining
`perf_token_batch` entries from the merged queue before closing.

### Race 3: orphan detection incorrectly marks a completed query as failed
**Window**: SSE generator calls `replay_existing()` → returns "running", then between this
and `is_task_active_any_instance()` the runner completes and clears the task_active flag.
**Fix** (`backend/streaming/sse_session.py`): `handle_orphaned_query` re-reads DB status;
if already terminal, returns the existing status without any UPDATE. UPDATE uses
`.where(status.in_(['running', 'received']))` guard; on 0 rows re-reads to return true status.

### Race 4: duplicate done events (runner vs cancel endpoint)
**Fix**: Atomic `UPDATE WHERE status='running' RETURNING thread_id` — only one writer
gets rows, only that writer calls `emit_done()`.

### Race 5 (CRITICAL): `cleanup_thread_session` destroys `done`-event drain recovery
**Window**: After `emit_done()` calls `push_pending_notify(done)`, the runner immediately
calls `cleanup_thread_session()` which was deleting `notify_pending:{thread_id}`.  If the
`done` Pub/Sub message was lost (network gap, fanout reconnect), the SSE generator's 25-second
drain cycle would call `drain_pending_notify()` and find an empty hash → it could only yield
pings forever, leaving the frontend in a permanent loading state (never completed).
**Fix** (`backend/db/redis/lock_manager/session_cleanup.py`): removed `_pending_key(thread_id)`
from the `cleanup_thread_session` key list.  The hash carries its own TTL (~19 min) and is
cleared only by `clear_pending_notify()` in the SSE `finally` block.

### Race 6: Watch stuck on first task — tokens suppressed for sequential later tasks
**Window**: Watch auto-registration used `not await is_thread_watching()` guard, so once the
first task set the watch the subsequent tasks' `started` events never updated it.  For
sequential fin-analysis tasks (query_optimizer → market_data_collector → decision_maker), all
tokens after the first task were silently suppressed.
**Fix** (`backend/api/stream.py`): removed the `not is_thread_watching()` guard from the live
`started` auto-registration.  The watch now always follows the **latest** started task.  The
user can still override via `PUT /stream/{thread_id}/watch`.

### `notify_pending` Key Ownership
| Action | Who | When |
|--------|-----|------|
| Create entry | `push_pending_notify()` | after each pg_notify emit |
| Delete one entry | `ack_pending_notify()` | SSE generator on receipt |
| Delete entire hash | `clear_pending_notify()` | SSE `finally` block on clean close |
| TTL expiry | Redis | ~19 min after last push (fallback if client never reconnects) |
| **NOT deleted by** | `cleanup_thread_session()` | (intentional — would destroy drain recovery) |

---

## SSE Event Reference

| Event | Channel | Fired by | Frontend handler |
|-------|---------|----------|-----------------|
| `connected` | (inline) | SSE generator on connect | — |
| `query_received` | lifecycle | `emit_query_received()` | `onQueryReceived` → POST /ack |
| `query_ack_confirmed` | lifecycle | `emit_query_ack_confirmed()` | `onQueryAckConfirmed` → stop retrying |
| `query_status` | lifecycle | `emit_query_status()` | `onQueryStatus` → phase label |
| `started` | lifecycle | `create_task()` | `onStarted` → add task to list |
| `token` | Redis Stream | `stream_text_task` / `stream_llm_task` | `onToken` → append to buffer |
| `perf_token_batch` | Redis Stream | `stream_perf_text_task` | `onPerfTokenBatch` → count += batch.count |
| `perf_concurrent_status` | Redis Stream | `dynamic_reader_gen` | `onPerfConcurrentStatus` → metrics panel |
| `perf_ingest_progress` | lifecycle | `emit_perf_ingest_progress()` | `onPerfIngestProgress` → progress bar |
| `perf_ingest_complete` | lifecycle | `emit_perf_ingest_complete()` | `onPerfIngestComplete` → ingest done |
| `completed` | lifecycle | `complete_task()` | `onCompleted` → mark task done |
| `failed` | lifecycle | `fail_task()` | `onFailed` → show error |
| `cancelled` | lifecycle | `cancel_task()` | `onCancelled` → terminate |
| `perf_test_stopped` | lifecycle | `emit_perf_test_stopped()` | `onPerfTestStopped` → timeout |
| `perf_test_complete` | lifecycle | `emit_perf_test_complete()` | `onPerfTestComplete` → completed |
| `done` | lifecycle | `emit_done()` | `onDone` → close stream |
| `ping` | (inline) | 25s timeout | — |

---

## Adding a New Feature Checklist

1. **Decide the flow**: streaming (Redis Streams + Pub/Sub) or non-streaming (REST/SSE lifecycle)?
2. **DB write + notify**: use `pg_notify_in_session()` inside the same transaction for atomicity.
3. **Ephemeral event** (no DB write): use `pg_notify()` autocommit raw connection.
4. **High-frequency token data** (>10 events/s): use `stream_token()` → Redis Streams.
5. **Frontend event handler**: add `es.addEventListener('my_event', ...)` in `stream.ts`.
6. **SSE generator passthrough**: verify `event_type` is not accidentally suppressed by the watch filter in `stream.py` (only `token` events are filtered).
7. **Pending-notify store**: push lifecycle events via `push_pending_notify()` so the 25s drain cycle recovers missed deliveries.
8. **Race guards**: if the new event could race with `done`, handle ordering explicitly.
