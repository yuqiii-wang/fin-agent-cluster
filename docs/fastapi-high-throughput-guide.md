# FastAPI + Celery High-Throughput Streaming Guide

A practical guide derived from building and optimising a real-time LLM-streaming
fintech service (FastAPI + LangGraph + Celery + Redis + PostgreSQL).

---

## 1. Architecture Separation of Concerns

The single most important decision in a high-throughput streaming system is
**which transport carries which event type**.  Mixing them causes unnecessary
coupling and prevents independent scaling.

### The two-channel rule

| Channel | What goes here | Why |
|---|---|---|
| **Redis Streams** (`XADD`/`XREAD`) | High-frequency token events | Persistent, ordered, supports consumer groups, zero DB cost per message |
| **PostgreSQL NOTIFY** → **Redis Pub/Sub** | Low-frequency lifecycle events (`started`, `completed`, `failed`, `done`) | Authoritative after DB commit, ephemeral delivery is fine because DB is the source of truth |

**Never** route lifecycle events through Redis Streams (adds unnecessary consumer-group overhead) and never route tokens through PG NOTIFY (8 KB payload limit, high-value DB connections wasted).

### Celery's actual role

```
Celery workers:   backend/streaming/workers/  ← batch Redis Stream consumers ONLY
FastAPI event loop: LangGraph graph execution, all asyncio graph tasks, SSE delivery
```

Celery is **not** involved in SSE delivery or graph execution.  It handles
offline batch consumers that read from the same Redis Streams after the SSE
session ends.

**Critical caution**: Celery workers **cannot hold SSE connections**.
`EventSourceResponse` requires a live HTTP connection that persists for minutes.
A Celery task has no HTTP socket to write to.  Any design that tries to route
SSE through Celery requires a third service that does what FastAPI already does —
it adds latency and complexity with no benefit at typical scale.

---

## 2. Connection Scaling — The O(N) PG Problem

### The anti-pattern

Every SSE subscriber opens a dedicated `psycopg3 AsyncConnection` for
`LISTEN "task_events:<thread_id>"`.

```
N active SSE sessions = N PG connections
100 concurrent users = 100 PG LISTEN connections
```

PostgreSQL default `max_connections = 100`.  At 100 concurrent users you hit
the limit.  Even before that, each connection costs ~5 MB of shared memory.

### The fix: single shared channel + Redis Pub/Sub fanout

```
                 ONE psycopg3 connection
                 LISTEN "sse_lifecycle"
                        │
                 lifecycle_fanout.py
                (asyncio.create_task — runs for app lifetime)
                        │ PUBLISH lifecycle:<thread_id>
                        ▼
                 Redis Pub/Sub (N subscribers, one TCP connection each to Redis)
                        │
                N × lifecycle_subscriber.read_lifecycle()
                        │
                N × SSE generators
```

Every `pg_notify` call now goes to the **same** channel `"sse_lifecycle"`.
The payload must contain `thread_id` so the fanout can route it.

```python
# channel.py — auto-inject thread_id on every pg_notify
async def pg_notify(thread_id: str, payload: dict[str, Any]) -> None:
    if "thread_id" not in payload:
        payload = {**payload, "thread_id": thread_id}   # copy, never mutate caller's dict
    await conn.execute("SELECT pg_notify(%s, %s)", [SHARED_LIFECYCLE_CHANNEL, raw])
```

**Connection budget after fix**:

| Connection type | Before (N=100) | After (N=100) |
|---|---|---|
| PG LISTEN connections | 100 | **1** |
| Redis Pub/Sub connections | 0 | 100 (cheap, ~1 KB each) |

### Fanout reconnect pattern

The fanout task must reconnect automatically on PG errors:

```python
async def _fanout_loop(redis_client) -> None:
    delay = 1.0
    while True:
        try:
            conn = await AsyncConnection.connect(PG_URL, autocommit=True)
            await conn.execute('LISTEN "sse_lifecycle"')
            delay = 1.0  # reset back-off on successful connect
            async for notification in conn.notifies(timeout=30.0):
                payload = json.loads(notification.payload)
                thread_id = payload.get("thread_id")
                await redis_client.publish(f"lifecycle:{thread_id}", notification.payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)   # exponential back-off, cap at 60 s
```

**Caution**: Never use a `time.sleep` grace period or hardcoded delay between
reconnect attempts.  Use exponential back-off with a cap.

---

## 3. SSE Generator Performance

### The per-token `is_disconnected()` trap

Starlette's `request.is_disconnected()` creates an `anyio` cancel scope and
issues an ASGI `receive()` call on **every invocation while the client is connected**.
This is intentional for single checks, but catastrophic if called per token.

```python
# BAD: is_disconnected() called once per token inside a 50-item batch
for raw in batch:          # batch size = 50
    ...
    if await request.is_disconnected():   # ← 50 cancel scopes per batch
        break
    yield raw

# GOOD: check once before the batch
if await request.is_disconnected():       # ← 1 cancel scope per batch
    break
for raw in batch:
    yield raw
```

With `_MAX_BATCH = 50` this cuts the cancel-scope overhead by **50×** during
active streaming.

### The `asyncio.wait_for` timer overhead

`asyncio.wait_for(coro, timeout)` always installs a deadline `TimerHandle` even
when the awaitable completes immediately.  During active token streaming the
merged queue almost always has items — paying for timer setup/teardown every
iteration is waste.

```python
# BAD: always pays for timer setup even when queue is full
raw = await asyncio.wait_for(merged.get(), timeout=25.0)

# GOOD: fast-path when items available; wait_for only when queue is empty
try:
    raw = merged.get_nowait()         # O(1), no timer
except asyncio.QueueEmpty:
    raw = await asyncio.wait_for(merged.get(), timeout=25.0)
```

### Batch size and event-loop fairness

Always cap batch size so the event loop can service new HTTP requests between
batches.  A batch of 500 tokens processed synchronously stalls every other
coroutine for ~50 ms.

```python
_MAX_BATCH = 50   # tune based on token size and target latency

batch: list[str] = [raw]
for _ in range(_MAX_BATCH - 1):
    try:
        batch.append(merged.get_nowait())
    except asyncio.QueueEmpty:
        break

# Process batch …

await asyncio.sleep(0)  # yield to event loop between batches
```

`asyncio.sleep(0)` is the canonical way to yield without sleeping; it reschedules
the current coroutine at the end of the ready queue.

---

## 4. Redis Streams — Publish and Subscribe Patterns

### Publisher: one client, reused across calls

Do **not** create a new Redis client per token.  Create one lazily and reuse it:

```python
_client: aioredis.Redis | None = None

async def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _client
```

**Caution (Celery)**: Celery tasks each run inside `asyncio.run()` which creates
and **destroys** a new event loop.  The reused client's connection pool is bound
to the old loop and raises `RuntimeError` on the next call.  Detect loop changes:

```python
_loop_id: int | None = None

async def _get_client() -> aioredis.Redis:
    global _client, _loop_id
    current_id = id(asyncio.get_running_loop())
    if _client is not None and _loop_id != current_id:
        await _client.aclose()
        _client = None
    if _client is None:
        _client = aioredis.from_url(REDIS_URL, decode_responses=True)
        _loop_id = current_id
    return _client
```

### Subscriber: XREAD BLOCK with a reasonable block timeout

```python
results = await client.xread({key: last_id}, block=2_000, count=100)
```

- `block=2_000` ms: the pump wakes at most every 2 s when idle, allowing clean
  cancellation without the `block=0` (forever) risk.
- `count=100`: read up to 100 entries per call — batching on the Redis side.
- Start from `"$"` (newest) not `"0"` (beginning) unless you need replay.

### Stream trimming

Always trim streams to prevent unbounded growth:

```python
await client.xadd(key, {"data": raw}, maxlen=10_000, approximate=True)
```

`approximate=True` (`~`) lets Redis defer the trim slightly for performance.
Delete the stream entirely when the session ends:

```python
await client.delete(stream_key(thread_id))
```

### Redis Pub/Sub vs Redis Streams

| | Redis Pub/Sub | Redis Streams |
|---|---|---|
| Delivery | Fire-and-forget; missed if no subscriber | Persistent; consumers can replay from any offset |
| Ordering | No | Yes (entry IDs) |
| Consumer groups | No | Yes |
| Memory | None (ephemeral) | Grows until trimmed |
| Best for | Lifecycle events (few/session, ephemeral OK) | Token events (many/session, replay needed) |

**Use Pub/Sub** when: ephemeral delivery is acceptable and the DB is the source of truth (lifecycle events).  
**Use Streams** when: you need persistence, replay, or consumer groups (token events, batch workers).

---

## 5. PostgreSQL NOTIFY — Cautions and Limits

### Hard limits

| Limit | Value | Notes |
|---|---|---|
| Payload size | 8,000 bytes | JSON-encode and check; truncate `output` field if over |
| Channel name length | 63 characters | UUID (36) + prefix (12) = 48 — safe |
| Connections (default) | 100 | The O(N) problem described above |

### Transaction timing matters

`NOTIFY` inside a transaction is **deferred until `COMMIT`**.  This is a feature —
it guarantees that DB writes are visible before subscribers act on the notification.

```python
# CORRECT: notify inside the session; pg delivers it when session.commit() fires
await pg_notify_in_session(session, thread_id, payload)
await session.commit()     # ← NOTIFY is delivered here

# CORRECT: notify after commit (autocommit connection)
await session.commit()
await pg_notify(thread_id, payload)  # ← delivered immediately
```

**Caution**: `pg_notify` with `autocommit=True` fires immediately regardless of
any surrounding application logic.  If you call it before your DB write is committed
on another connection, subscribers may query the DB and find stale data.

### Shared channel + thread_id injection

When using a single shared NOTIFY channel across all threads, every payload **must**
contain `thread_id`.  The safest approach is to inject it at the transport layer
(not at every call site), using a dict copy:

```python
if "thread_id" not in payload:
    payload = {**payload, "thread_id": thread_id}   # new dict, caller's dict unchanged
```

Never mutate the caller's dict — it may be logged or reused.

---

## 6. Lifecycle Event Delivery Guarantee (Ack Store)

NOTIFY delivery is best-effort.  If the SSE generator is not yet subscribed when
`pg_notify` fires, the event is lost.  The solution is a **Redis hash ack store**:

```
emit lifecycle event
  1. pg_notify(thread_id, payload)            # deliver to live subscriber
  2. push_pending_notify(thread_id, event, raw)  # backup in Redis hash
                                                  # TTL = full retry schedule + headroom

SSE generator receives event
  3. yield to client
  4. ack_pending_notify(thread_id, event)     # HDEL from Redis hash

SSE generator 25 s timeout (no events)
  5. drain_pending_notify(thread_id)          # HGETALL — find unacked entries
  6. For each entry within TTL: put_nowait(merged)  # re-emit
  7. increment_task_step_retry(task_id, event)      # audit log
```

This gives at-least-once delivery without requiring persistent message queues or
complex state machines.

**Caution**: The drain cycle fires on the 25 s idle timeout, not continuously.
If your graph emits a lifecycle event and the SSE generator is not yet started
(cold-connect race), the event will be recovered on the first drain — not
instantaneously.  For UX-critical events, ensure the client connects before ACKing
the query.

---

## 7. asyncio Task Management

### Graph execution as `asyncio.Task`

LangGraph graph execution runs as a plain `asyncio.create_task(run_graph_async(...))`.
This means:

- All LLM calls, DB I/O, and Redis XADD are co-operatively scheduled.
- Multiple concurrent queries interleave at every `await` — there is no CPU
  parallelism, only I/O concurrency.
- **GIL is still held** during pure Python computation inside nodes.

For CPU-bound preprocessing (e.g. NumPy/Pandas in quant nodes) consider
`asyncio.to_thread(fn)` or a `ProcessPoolExecutor`.

### Task registry

Keep a `dict[str, asyncio.Task]` (`running_tasks`) indexed by `thread_id`.
This is the only authoritative source of whether a graph is currently running.

```python
running_tasks: dict[str, asyncio.Task] = {}

task = asyncio.create_task(run_graph_async(thread_id, ...))
running_tasks[thread_id] = task
task.add_done_callback(lambda t: running_tasks.pop(thread_id, None))
```

**Cancellation**: `task.cancel()` raises `asyncio.CancelledError` inside the
running coroutine at the next `await`.  The graph must handle this explicitly:

```python
try:
    await graph.ainvoke(...)
except asyncio.CancelledError:
    await fail_task(thread_id, task_id, "cancelled")
    await emit_done(thread_id, "cancelled")
    raise   # re-raise so asyncio marks the task as cancelled
```

Never swallow `CancelledError` — this breaks `asyncio.Task.cancel()` semantics
and causes memory leaks (tasks that never finish).

### Lifespan background tasks

Start long-lived background tasks in the FastAPI lifespan context manager, not
in a `startup` event handler:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _fanout_task = asyncio.create_task(run_lifecycle_fanout())
    _fallback_tasks = await start_fallback_workers()
    yield
    _fanout_task.cancel()
    for t in _fallback_tasks:
        t.cancel()
```

`yield` is the clean shutdown boundary.  Tasks started here are cancelled before
the event loop closes.

---

## 8. Celery on WSL2 / Linux (Prefork)

Celery on Linux uses the **prefork** pool by default (separate OS processes via
`os.fork()`).  Each worker process runs its own Python interpreter.

### Event loop rules with prefork

`asyncio.run()` inside a Celery task creates a **fresh event loop** per call.
This means:

- Module-level `asyncio` resources (clients, connections) are **not shared** across tasks.
- Any `redis.asyncio.Redis` client created at import time belongs to the main process's
  loop — forked workers must recreate it.  Use loop-id detection (see §4).
- Coroutines cannot be `await`-ed across the fork boundary.

**Pattern**: Celery tasks that need async I/O should call `asyncio.run(my_async_fn())`.
Keep the async function self-contained; do not rely on module-level async state.

### Celery workers ≠ SSE holders

Celery workers process jobs from a queue and return results.  They terminate their
task function and release the worker process.  An SSE stream must remain open for
the full duration of a query (seconds to minutes).

If you need to push events from a Celery task to a client, the only correct
patterns are:
1. Publish to Redis; the FastAPI SSE generator reads from Redis (current architecture).
2. Webhook / callback URL that the client polls or subscribes to separately.

Never attempt to hold an HTTP connection inside a Celery task.

---

### 8.2 Dedicated queues per stream type

All stream-consumer tasks sharing a single queue (default: `celery`) compete for
the same pool of worker slots.  A slow batch (e.g. `QUANT_COMPUTE` running
pandas-ta + DB upsert for 20 rows) can hold both slots for hundreds of
milliseconds and starve `GRAPH_EVENTS`, which drives SSE token delivery on a 2 s
poll interval.

The fix is to isolate workloads into three named queues and start a **dedicated
worker process per queue**:

| Queue | Topics | Concurrency | Characteristic |
|---|---|---|---|
| `stream:critical` | `GRAPH_EVENTS` | `N + 2` | Low-latency SSE driver; always-healthy worker holds beat |
| `stream:default` | `MARKET_TICKS`, `TRADE_SIGNALS` | `N` | Regular ingestion cadence |
| `stream:compute` | `QUANT_COMPUTE` | `min(N, 2)` | CPU/IO-heavy; capped to limit system pressure |

Each `StreamTopicConfig` carries a `queue` field:

```python
# backend/streaming/config.py
QUEUE_CRITICAL = "stream:critical"
QUEUE_DEFAULT  = "stream:default"
QUEUE_COMPUTE  = "stream:compute"

GRAPH_EVENTS = StreamTopicConfig(
    ...,
    task_path="backend.streaming.workers.graph_events.consume_batch",
    queue=QUEUE_CRITICAL,
)
```

The beat schedule injects `options: {queue: topic.queue}` so beat dispatches
directly to the correct worker:

```python
_beat_schedule = {
    f"poll-{topic.human_key}": {
        "task": topic.task_path,
        "schedule": topic.beat_interval,
        "options": {"queue": topic.queue},   # ← dispatches to dedicated pool
    }
    for topic in ACTIVE_TOPICS if topic.task_path
}
```

`run.py` starts three workers (one per queue) instead of one:

```python
_worker_specs = [
    ("stream:critical", "critical", concurrency + 2, True),   # embed beat on Unix
    ("stream:default",  "default",  concurrency,     False),
    ("stream:compute",  "compute",  min(concurrency, 2), False),
]
```

**Caution**: on Unix the `stream:critical` worker embeds `--beat`.  Beat must
run on the most reliable worker (the one that is guaranteed to stay alive) to
prevent gaps in the poll schedule.  Do not embed beat on the compute worker —
a CPU-heavy batch can stall beat's scheduler loop.

---

## 9. Kong API Gateway — SSE Requirements

Kong buffers responses by default.  For SSE routes this must be disabled or
tokens will only arrive at the client in large chunks (when Kong's buffer fills).

```yaml
# kong-api-gateway/api/v1/stream/routes.yml
routes:
  - name: route-stream
    service: fastapi
    paths: [/api/v1/stream]
    response_buffering: false   # ← required for SSE
```

Also ensure upstream and service timeouts match your longest possible query:

```yaml
services:
  - name: fastapi
    write_timeout: 3600000   # 60 min in ms
    read_timeout: 3600000
```

**Caution**: The CORS plugin must expose `Last-Event-ID` for SSE reconnect to work:

```yaml
plugins:
  - name: cors
    config:
      exposed_headers: [Last-Event-ID]
```

### HTTP/2 on the SSE port — removing the browser 6-connection limit

Under HTTP/1.1, browsers enforce a **6-connection-per-origin** limit.  When a
user launches N concurrent SSE streams from the same origin (e.g. a perf-test
panel firing 10 simultaneous requests), only 6 `EventSource` connections open
immediately; the remaining N−6 queue in the browser's TCP stack and stall until
a slot frees.  The symptom is: all N queries are accepted by the backend (all N
DB rows created, all N `query_received` events emitted within milliseconds), but
only 6 `client_connected` log lines appear in wave 1.

The fix is **HTTPS + HTTP/2** on Kong's SSE port.  HTTP/2 multiplexes all
`EventSource` connections over a **single** TCP connection, removing the
per-origin cap entirely.

```yaml
# docker-compose.yml
kong:
  environment:
    KONG_PROXY_LISTEN: "0.0.0.0:8000, 0.0.0.0:8889 ssl http2"
    KONG_SSL_CERT: /etc/kong/certs/localhost.crt
    KONG_SSL_CERT_KEY: /etc/kong/certs/localhost.key
  volumes:
    - ./certs:/etc/kong/certs:ro
```

Generate a self-signed cert with SAN entries so the browser trusts it:

```bash
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout certs/localhost.key -out certs/localhost.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Point the frontend at the HTTPS port:

```
VITE_SSE_URL=https://localhost:8889
```

Verify HTTP/2 is active:

```bash
curl -sk --http2-prior-knowledge https://localhost:8889/ -o /dev/null -w "%{http_version}\n"
# → 2
```

**One-time browser step**: visit `https://localhost:8889` once and accept the
self-signed cert ("Advanced → Proceed").  After that, `EventSource` connections
from the app are trusted without any browser warnings.

**Caution**: Add `certs/` to `.gitignore` so private keys are never committed.

---

## 10. Summary: Bottleneck Checklist

When a streaming system is slower than expected, check in this order:

| # | Symptom | Likely cause | Fix |
|---|---|---|---|
| 1 | High CPU in FastAPI, not in LLM | `is_disconnected()` called per token | Call once per batch |
| 2 | High async overhead at idle | `wait_for` timer on every loop iteration | `get_nowait()` fast-path |
| 3 | DB connection limit hit | Per-subscriber PG LISTEN | Single shared channel + Redis Pub/Sub fanout |
| 4 | Redis memory growing | Streams not trimmed or deleted | `MAXLEN ~`, `DEL` on session end |
| 5 | Tokens arrive in bursts, not smoothly | `block=0` XREAD or no batch cap | `block=2000`, `_MAX_BATCH` cap |
| 6 | Events lost on cold-connect | No ack store | Redis hash pending-notify with drain cycle |
| 7 | Celery worker crash on async | Stale event loop after fork | Loop-id detection before reusing clients |
| 8 | Kong drops long responses | `response_buffering` default | Set `response_buffering: false` on SSE routes |
| 9 | `asyncio.CancelledError` silently swallowed | Missing `raise` in except | Always re-raise `CancelledError` |
| 10 | Event loop stalled during burst | Batch without `sleep(0)` yield | `await asyncio.sleep(0)` between batches |
| 11 | Only 6 of N concurrent SSE sessions connect immediately | Browser HTTP/1.1 6-conn-per-origin limit | Enable HTTPS + HTTP/2 on Kong's SSE port |
| 12 | Stale `EventSource` objects accumulate after sessions end | No explicit `es.close()` on terminal events | Call cleanup/dequeue in every terminal handler |
| 13 | `GRAPH_EVENTS` poll delayed by compute batch | All stream tasks share one Celery queue | Dedicated queues: `stream:critical`, `stream:default`, `stream:compute` |
| 14 | UI jank / high JS CPU during token stream | `setMessages` called per token (~100 renders/sec) | Buffer tokens in refs, flush to React state every 100 ms |
| 15 | `scrollIntoView` fires every 100 ms during streaming | Scroll dep is full `messages` array | Change dep to `messages.length`; wrap `MessageList` and `NodeList` with `React.memo` |

---

## 11. Frontend EventSource Lifecycle Management

### The browser 6-connection limit and HTTP/2

Browsers cap HTTP/1.1 connections to **6 per origin**.  Each `EventSource`
occupies one slot.  With 10 concurrent sessions, 4 are queued until a slot
frees — they appear connected to the backend (query accepted, DB row created)
but the SSE stream does not open.

Enabling HTTP/2 on the SSE origin removes this cap because all `EventSource`
streams are multiplexed over one TCP connection.  See §9 for Kong configuration.

### Explicit dequeue on terminal events

The browser will not garbage-collect an `EventSource` object until all references
to it are dropped **and** the connection is explicitly closed.  If a terminal
event (`done`, `failed`, `perf_test_complete`) is received but `es.close()` is
not called, the connection lingers in `OPEN` state and continues to occupy an
HTTP/2 stream (or, under HTTP/1.1, one of the 6 TCP slots).

**Pattern**: every terminal event handler must call `es.close()` before updating
application state.

```typescript
// BAD: terminal event received, EventSource left open
onDone: (data) => {
  setStatus("done");          // ← connection still open
},

// GOOD: close first, then update state
onDone: (data) => {
  esCleanup?.();              // calls es.close() immediately
  esCleanup = null;
  setStatus("done");
},
```

### Shared cleanup registry pattern (multi-session)

When N sessions run concurrently (e.g. perf-test panel), keep a `Map<thread_id,
() => void>` of cleanup functions.  A `dequeue()` helper that removes an entry
from the map makes `freezeAll` and a subsequent `closeSession` both idempotent:

```typescript
const cleanups = useRef<Map<string, () => void>>(new Map());

// On stream open:
const cleanup = openStream(thread_id, handlers);
let esCleanup: (() => void) | null = cleanup;
cleanups.current.set(thread_id, cleanup);

// dequeue — call at the start of every terminal handler:
const dequeue = () => {
  esCleanup?.();
  esCleanup = null;
  cleanups.current.delete(thread_id);   // freezeAll will skip this session
  clearTimeout(timeouts.current.get(thread_id));
  timeouts.current.delete(thread_id);
};

// freezeAll — safe: sessions already dequeued are no-ops
const freezeAll = () => {
  cleanups.current.forEach((fn) => fn());
  cleanups.current.clear();
};
```

### Unified hook for session lifecycle management

Implement a **single hook** that handles all lifecycle logic (ACK handshake,
phase-transition status, ingest/pub events, terminal handlers). This ensures:

- Dequeue logic is written once.
- Safety-timeout and cleanup-registry wiring is not duplicated.
- Terminal event coverage is consistent.

```typescript
export function usePerfSession(deps: PerfSessionDeps): UsePerfSessionReturn {
  const openSessionStream = useCallback((thread_id: string) => {
    const mode = "browser";
    let esCleanup: (() => void) | null = null;

    const dequeue = () => { esCleanup?.(); esCleanup = null; /* ... */ };

    const cleanup = openStream(thread_id, {
      // shared handlers
      onDone: (data) => { dequeue(); closeSession(thread_id, ...); },
      onFailed: (data) => { dequeue(); closeSession(thread_id, "failed"); },

      // browser-mode handlers
      onPerfTokenBatch: (data) => { /* ... */ },
    });

    esCleanup = cleanup;
  }, [...]);
}
```

---

## 12. Multi-Instance Deployment (Two Uvicorn Instances)

`run.py` now launches N uvicorn instances (default 2) as subprocesses on
consecutive ports (`FASTAPI_PORT`, `FASTAPI_PORT+1`, …) and Kong round-robins
across both targets:

```python
# run.py — __main__
uvicorn_procs = _start_uvicorn_instances(
    base_port=settings.FASTAPI_PORT,
    count=args.instances,   # --instances N, default 2
    log_config_path=log_config_path,
)
```

```yaml
# kong-api-gateway/_shared/upstreams.yml
targets:
  - target: "{BACKEND_HOST}:{BACKEND_PORT}"    # port 8432
    weight: 100
  - target: "{BACKEND_HOST}:{BACKEND_PORT_2}"  # port 8433
    weight: 100
```

`BACKEND_PORT_2` defaults to `BACKEND_PORT + 1` and is resolved by `build.py`
alongside all other `{PLACEHOLDER}` tokens.

Running two FastAPI/Uvicorn instances behind Kong exposes all per-process
in-memory state as split-brain risks.  This section catalogues every state
location, classifies it, and prescribes the minimal fix.

### 12.1 State tier map

#### Already safe — PostgreSQL (authoritative, shared)

| Table | What it captures |
|---|---|
| `user_queries` | Full query lifecycle, `status`, `is_ack`, `ack_at`, `retry_count`, perf params |
| `tasks` | Sub-task status, input/output |
| `streamings` | Per-task delivery audit — `status`, `is_ack`, `ack_at`, `retry_count` |
| `node_executions` | Node I/O + timing |
| `checkpoints*` | Full LangGraph graph state |

`streamings.is_ack + retry_count` is the DB-level mirror of the `notify_pending:{thread_id}` Redis hash.  The DB is the authoritative audit trail; Redis is the operational retry scheduler (stores `next_retry_at` timing and raw payload).

#### Already safe — Redis (operational, shared)

| Key pattern | Purpose |
|---|---|
| `tokens:{thread_id}` | LLM token stream (ephemeral, XADD/XREAD) |
| `notify_pending:{thread_id}` | pg_notify retry envelopes + `next_retry_at` timing |
| `fin:query:phase:{thread_id}` | Fine-grained phase sub-state (`preparing`/`ingesting`/`sending`) |
| `lifecycle:{thread_id}` | Pub/Sub relay channel for SSE generators |

All of these already live in Redis and are instance-agnostic.

#### **Broken** — in-process Python dicts

| Variable | Module | Risk |
|---|---|---|
| `_watch_registry: dict[str, int]` | `streaming/sse_session.py` | `PUT /watch` on instance A; SSE generator on instance B sees `{}` → all tokens suppressed |
| `running_tasks: dict[str, asyncio.Task]` | `api/registry.py` | `POST /cancel` on non-owning instance is a silent no-op; `GET /status` returns `is_active=False` wrongly |

#### **Broken** — background singleton with no leader election

| Task | Module | Risk |
|---|---|---|
| `run_lifecycle_fanout` | `main.py` / `db/redis/lifecycle_fanout.py` | Both instances LISTEN on `sse_lifecycle` and PUBLISH to `lifecycle:{thread_id}` → every SSE subscriber receives each lifecycle event **twice** |

---

### 12.2 Fix: `_watch_registry` → Redis String

Replace the process-local dict with a Redis String.  The watch is per-session
and short-lived, so a 1-hour TTL is more than sufficient.

```python
# Before (process-local, breaks under multiple instances)
_watch_registry: dict[str, int] = {}

# After — reads/writes go to Redis
_WATCH_PREFIX = "watch:"
_WATCH_TTL = 3600

async def register_watch(thread_id: str, task_id: int) -> None:
    client = await _get_publish_client()
    await client.setex(f"{_WATCH_PREFIX}{thread_id}", _WATCH_TTL, task_id)

async def unregister_watch(thread_id: str) -> None:
    client = await _get_publish_client()
    await client.delete(f"{_WATCH_PREFIX}{thread_id}")

async def get_watched_task(thread_id: str) -> int | None:
    client = await _get_publish_client()
    val = await client.get(f"{_WATCH_PREFIX}{thread_id}")
    return int(val) if val is not None else None

async def is_thread_watching(thread_id: str) -> bool:
    client = await _get_publish_client()
    return await client.exists(f"{_WATCH_PREFIX}{thread_id}") == 1
```

---

### 12.3 Fix: `running_tasks` — choose one strategy

An `asyncio.Task` object is bound to one event loop and cannot be serialized or
shared.  Two strategies exist; pick based on deployment complexity budget.

#### Option A — Kong sticky sessions (recommended, zero code change)

Hash `thread_id` in the Kong upstream to route all requests for the same thread
to the same instance:

```yaml
# kong-api-gateway/_shared/upstreams.yml
upstreams:
  - name: fastapi-upstream
    algorithm: consistent-hashing
    hash_on: header
    hash_on_header: X-Thread-Id   # set by frontend on every request
```

The frontend already sends `thread_id` in the URL (`/stream/{thread_id}`,
`/query/{thread_id}/cancel`).  Kong can hash on the URI path instead:

```yaml
    hash_on: uri_capture
    hash_fallback: ip   # fallback when thread_id not in URI
```

All cancel, watch, and status requests for a given thread land on the instance
that owns the `asyncio.Task` — no code change required.

#### Option B — Redis Pub/Sub cancel signal (~40 lines)

When sticky sessions are not possible, publish a cancel message to Redis; each
instance subscribes and cancels local tasks on receipt:

```python
# On POST /query/{thread_id}/cancel
await redis_client.publish(f"cancel:{thread_id}", reason)

# Background subscriber (started in lifespan)
async def _cancel_listener() -> None:
    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("cancel:*")
    async for msg in pubsub.listen():
        if msg["type"] != "pmessage":
            continue
        thread_id = msg["channel"].removeprefix("cancel:")
        task = running_tasks.pop(thread_id, None)
        if task and not task.done():
            task.cancel()
```

For `GET /stream/{id}/status`, replace `is_task_active()` with a DB check:
`user_queries.status == 'running'` is the authoritative signal.

---

### 12.4 Fix: lifecycle fanout leader election

Without a leader lock both instances publish every lifecycle notification twice.
Use a Redis `SET … NX` lock with a renewal loop:

```python
import uuid, asyncio
from redis.asyncio import Redis

_FANOUT_LOCK_KEY = "lock:lifecycle_fanout"
_LOCK_TTL = 30          # seconds; must be > renewal_interval * 2
_RENEWAL_INTERVAL = 12  # seconds

async def run_lifecycle_fanout_with_leader_election(redis: Redis) -> None:
    """Only the instance holding the leader lock runs the fanout loop."""
    instance_id = str(uuid.uuid4())
    while True:
        acquired = await redis.set(
            _FANOUT_LOCK_KEY, instance_id,
            nx=True, ex=_LOCK_TTL,
        )
        if acquired:
            # This instance is leader — run fanout + renew lock concurrently.
            renewer = asyncio.create_task(_renew_lock(redis, instance_id))
            try:
                await _fanout_loop(redis)   # existing implementation
            finally:
                renewer.cancel()
                # Release only if we still own the lock.
                val = await redis.get(_FANOUT_LOCK_KEY)
                if val == instance_id:
                    await redis.delete(_FANOUT_LOCK_KEY)
        else:
            # Not the leader — wait and retry.
            await asyncio.sleep(_RENEWAL_INTERVAL)

async def _renew_lock(redis: Redis, instance_id: str) -> None:
    while True:
        await asyncio.sleep(_RENEWAL_INTERVAL)
        val = await redis.get(_FANOUT_LOCK_KEY)
        if val != instance_id:
            break   # lost the lock — fanout loop will be cancelled by finally block
        await redis.expire(_FANOUT_LOCK_KEY, _LOCK_TTL)
```

On leader crash the lock expires in `_LOCK_TTL` seconds; the standby instance
acquires it and resumes publishing.  There is no hardcoded sleep — the renewal
interval is a tunable constant.

---

### 12.5 Fix: dedup INSERT race — partial unique index

`POST /query` does a bare `SELECT` (no row-level lock) then `INSERT`.  Two
instances can both pass the dedup check concurrently within the 60-second window.
The cheapest fix is a DB-enforced constraint:

```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_user_queries_dedup
  ON fin_agents.user_queries (user_id, md5(query))
  WHERE status IN ('received', 'pending', 'running');
```

A duplicate `INSERT` raises `UniqueViolation`; the endpoint catches it and
returns a NACK (`status='cancelled'`) with the existing `thread_id`.  No Redis
involvement needed — the DB owns this invariant.

---

### 12.6 Summary

| Issue | Severity | Fix | Scope |
|---|---|---|---|
| `_watch_registry` in-process | **Critical** | Redis String `watch:{thread_id}` | ~20 lines |
| `running_tasks` cancel routing | **Critical** | Kong consistent-hash by thread_id (option A) or Redis Pub/Sub cancel (option B) | Kong config or ~40 lines |
| `lifecycle_fanout` double-publish | **Critical** | Redis leader-lock `SET lock:lifecycle_fanout NX EX 30` + renewal | ~50 lines |
| Dedup INSERT TOCTOU | **High** | `UNIQUE INDEX … WHERE status IN (…)` partial index | 1 SQL statement |
| `notify_pending:{thread_id}` | Already safe | Already in Redis | — |
| `fin:query:phase:{thread_id}` | Already safe | Already in Redis | — |
| `tokens:{thread_id}` Redis Streams | Already safe | Already in Redis | — |
| `lifecycle:{thread_id}` Pub/Sub | Already safe | Already in Redis | — |
| L1 `TimedLRUCache` (quant/news) | Low | Optional — L2 DB cache is already shared | — |
| `_token_stats`, `_xadd_count` | None | Metrics only — no correctness impact | — |

**Recommended deployment order**: fix the partial unique index first (zero
runtime risk, pure SQL), then move `_watch_registry` to Redis, then add the
fanout leader lock, then configure Kong sticky sessions.  The cancel Pub/Sub
option (B) is only needed if sticky sessions are not feasible.

---

## 13. React Token Rendering Optimisation

At 50+ tokens per second the SSE `token` event fires faster than the browser's
paint budget (~16 ms per frame).  Calling `setState` on every token creates
**100+ React re-renders per second**, each reconciling the full message list
and rebuilding every child component tree.

### The per-token `setState` trap

```typescript
// BAD: each SSE token event calls setMessages → React re-render
onToken: (data) => {
  appendMessageText(asstMsgId, token);        // setMessages()
  setTokenStreams((prev) => ({ ...prev }));    // setTokenStreams()
},
```

With a 2-task stream emitting 50 tokens/sec this produces **~100 `setState`
calls/sec**, each triggering a synchronous reconcile of the full message tree.

### The fix: ref buffers + 100 ms flush interval

Accumulate token deltas in plain `useRef` objects (no React overhead) and
flush both buffers in a single `setInterval` tick:

```typescript
// Buffer refs — never trigger React renders
const msgTextBufferRef = useRef<Record<string, string>>({});
const taskTokenBufferRef = useRef<Record<number, string>>({});

// pushTokenStream — called from onToken; zero React cost
const pushTokenStream = useCallback((taskId: number, token: string) => {
  taskTokenBufferRef.current[taskId] = (taskTokenBufferRef.current[taskId] ?? "") + token;
}, []);

// appendMessageText — called from onToken for llm_analysis tasks; zero React cost
const appendMessageText = useCallback((msgId: string, token: string) => {
  msgTextBufferRef.current[msgId] = (msgTextBufferRef.current[msgId] ?? "") + token;
}, []);

// Flush interval — at most 2 setState calls per 100 ms regardless of token rate
useEffect(() => {
  const id = setInterval(() => {
    const msgFlush = msgTextBufferRef.current;
    const taskFlush = taskTokenBufferRef.current;
    if (!Object.keys(msgFlush).length && !Object.keys(taskFlush).length) return;
    if (Object.keys(msgFlush).length) {
      msgTextBufferRef.current = {};
      setMessages((prev) =>
        prev.map((m) => {
          const pending = msgFlush[m.id];
          return pending ? { ...m, text: m.text + pending, streamingCursor: true } : m;
        })
      );
    }
    if (Object.keys(taskFlush).length) {
      taskTokenBufferRef.current = {};
      setTokenStreams((prev) => {
        const next = { ...prev };
        for (const [key, text] of Object.entries(taskFlush))
          next[Number(key)] = (next[Number(key)] ?? "") + text;
        return next;
      });
    }
  }, 100);
  return () => clearInterval(id);
}, []);
```

**Always clear the buffers** when starting or resetting a session to prevent
stale token deltas from a previous thread bleeding into the new one:

```typescript
msgTextBufferRef.current = {};
taskTokenBufferRef.current = {};
```

### Re-render reduction via `React.memo`

Even with the flush interval, one `setMessages` call per 100 ms still
re-renders `MessageList` and all its children.  Wrap components with
`React.memo` so they bail out when their specific props have not changed:

```typescript
// MessageList — re-renders only when messages array reference changes
export const MessageList = memo(function MessageList({ messages, onNodeClick }: Props) { ... });

// NodeList — re-renders only when nodes, tokenStreams, or onNodeClick change
export const NodeList = memo(function NodeList({ nodes, threadId, onNodeClick, tokenStreams }: Props) { ... });
```

During a token flush, `setMessages` creates a new array with one updated
assistant message object. However `msg.nodes` on that object is the **same
reference** as before (nodes are only mutated by `onStarted`/`onCompleted`
events, not by text flushes). `React.memo` compares `nodes` by reference and
skips re-rendering `NodeList` entirely.

### `scrollIntoView` — scope the scroll trigger

The auto-scroll effect that calls `scrollIntoView` should depend on
`messages.length`, **not** the full `messages` array:

```typescript
// BAD: fires on every text flush (100 ms)
useEffect(() => {
  bottomRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages]);

// GOOD: fires only when a new message is added
useEffect(() => {
  bottomRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages.length]);
```

With `[messages]`, every 100 ms token flush triggers a smooth scroll animation,
which forces layout recalculation and interferes with the user's ability to
scroll up to read earlier messages.

### Memoize expensive derived values in child components

Child components that derive JSX arrays from props should use `useMemo` to
avoid rebuilding them on unrelated re-renders:

```typescript
// BAD: items array with JSX rebuilt on every parent render
const items = nodes.map((node) => { ... });

// GOOD: only rebuilds when nodes, tokenStreams, or handleClick change
const items = useMemo(() => nodes.map((node) => { ... }), [nodes, tokenStreams, handleClick]);

// Stable event handler — prevents items memo from invalidating unnecessarily
const handleClick = useCallback((node: NodeGroup) => { ... }, [selectedNodeName, onNodeClick, executions, threadId]);

// Streaming text for selected node — only recomputes when relevant tasks change
const selectedStreamingText = useMemo(
  () => selectedNode?.tasks.filter((t) => t.status === "running").map((t) => tokenStreams[t.id] ?? "").join("") ?? "",
  [selectedNode, tokenStreams],
);
```

### Performance impact summary

| Metric | Before | After |
|---|---|---|
| `setState` calls/sec at 50 tok/s | ~100 | ≤ 20 (2 per 100 ms tick) |
| `NodeList` re-renders/sec | ~100 | 0 (memo + stable nodes ref) |
| `scrollIntoView` calls/sec | ~10 | 0 during streaming (length unchanged mid-stream) |
| `items` JSX rebuilt/sec | ~100 | 0 (memo invalidates only on node status change) |
