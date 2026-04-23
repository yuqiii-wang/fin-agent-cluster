---
name: perf-test
description: >
  Use when working on performance testing, load testing, or the StreamingPerfTestPanel.
  Covers the perf-test graph node, PerfIngest Celery app, and the
  frontend StreamingPerfTestPanel component.
---

# Streaming Performance Test — Architecture & Guide

## Trigger phrase

`DO STREAMING PERFORMANCE TEST NOW` — defined as `PERF_TEST_TRIGGER` in `backend/graph/builder.py`.

## Architecture overview

Perf-test queries go through the **same Celery per-thread queue** as normal queries.
`build_unified_graph()` routes internally via `_route_query`:

```
POST /query "DO STREAMING PERFORMANCE TEST NOW"
  └─ queries.py: asyncio.create_task(run_graph_async())   [FastAPI event loop]
       └─ build_unified_graph() → _route_query() → "perf_test_streamer"
            └─ perf_test_streamer node  (LangGraph, two-phase)
                 ├─ Phase 1: mock_ingest  (PERF_TEST_INGEST)
                 │    └─ run_ingest_first_half()  [XADD first N/2 tokens, no sentinel]
                 │         └─ complete_task() + emit_perf_ingest_half_complete() → pg_notify UI
                 └─ Phase 2: mock_pub  (PERF_TEST_PUB)
                      ├─ run_ingest_second_half()  [XADD remaining N/2 + sentinel]
                      │    └─ updates _ConcurrentProgress (ingest_tps, ingest_done)
                      └─ stream_perf_text_task(dynamic_reader_gen())
                           └─ adaptive batch_size → perf_token_batch SSE to tokens:{thread_id}
                                └─ emit_perf_test_complete/stopped() + emit_done()
```

Graph routing:
```
START ──(PERF_TEST_TRIGGER?)──► perf_test_streamer ──► END
      └──────────────────────► query_optimizer → market_data_collector → decision_maker ──► END
```

Perf params (`total_tokens`, `timeout_secs`) are Celery task kwargs → `PerfTestState`.

## Query-status phase tracking

| Phase | Emitted by | Frontend status label |
|---|---|---|
| `received` | `queries.py` after `apply_async` | Received |
| `preparing` | `runner.py` start of worker | Preparing |
| `ingesting` | `node.py` before phase 1 ingest | Ingesting |
| `sending` | `node.py` before phase 2 concurrent pub | Sending |

Phase stored in Redis `fin:query:phase:{thread_id}` (TTL 600 s) for late-connect replay.
Cleanup: `runner.py` and cancel endpoint both call `delete_query_phase`.

Frontend status flow:
```
connecting → received → preparing → ingesting → sending → completed/failed/stopped/cancelled
```
First `perf_token_batch` while in a pre-sending state auto-advances to `"sending"`.

## Two-Phase Concurrent Architecture

### Phase 1: `mock_ingest` (PERF_TEST_INGEST)

- `run_ingest_first_half()` bulk-writes first `total_tokens // 2` tokens to `fin:perf:{thread_id}` via async Redis pipeline (one round-trip per batch of 10,000). **No sentinel** appended yet.
- Emits `perf_ingest_progress` SSE ~every second.
- Task **completed** (not all tokens yet) — frontend notified via `perf_ingest_half_complete` pg_notify event.
- Task completion carries `{total_generated: N/2, stop_reason: "half_done", ingest_ms}`.

### Phase 2: `mock_pub` (PERF_TEST_PUB) — **concurrent**

Both coroutines run via `asyncio.gather` in the **same FastAPI asyncio event loop** so write and read for the same `thread_id` are co-located:

**`run_ingest_second_half()`**
- Continues XADD from `N/2+1..N`, then appends sentinel.
- Updates `_ConcurrentProgress.ingest_tps` (rolling 1-s window) and sets `ingest_done=True` when sentinel is written.
- Emits `perf_ingest_progress` SSE ~every second.

**`dynamic_reader_gen()`** (adaptive batch reader)
- **Warmup** (first 3 s): `batch_size = 1` (one token at a time).
- **Adaptive windows** (every 3 s thereafter):
  - Ingest active → scale `batch_size` to target `digest_tps ≈ 1.5 × ingest_tps`.
  - Ingest done → reduce toward `batch_size = 3`.
  - Stream backlog < 50 → clamp to `batch_size = 1`.
  - Stream exhausted + ingest done → exit generator.
- Uses blocking `XREAD(block=1000ms)` — yields asyncio event loop while waiting; no busy-wait.
- Emits `perf_concurrent_status` via Redis Streams every 3 s: `{batch_size, digest_tps, ingest_tps, stream_len}`.
- `stream_perf_text_task()` accumulates yielded tokens → `perf_token_batch` SSE (batches of 1,000).

### Stall recovery (beat)

PerfIngest beat fires `recover_stalled_streams` every 10 s. Picks the single oldest stalled session (no heartbeat > 30 s) and redispatches `bulk_ingest_stream` — drain-first: one at a time.

## PerfIngest Celery App

| Property | Value |
|---|---|
| Module | `backend.graph.agents.perf_test.celery_ingest.celery_app` |
| Broker | Redis DB 3 |
| Backend | Redis DB 4 |
| Beat task | `recover_stalled_streams` every 10 s |

```bash
celery -A backend.graph.agents.perf_test.celery_ingest.celery_app.perf_ingest_app worker --beat --loglevel=info
```

## Redis key layout

| Key | Type | Purpose |
|---|---|---|
| `fin:perf:{thread_id}` | Stream | Token entries + sentinel |
| `fin:perf:ingest:result:{thread_id}` | List | (legacy — not used in default path) |
| `fin:perf:ingest:state:{thread_id}` | Hash | `total_tokens, produced, status, heartbeat` |
| `fin:perf:ingest:active` | Sorted Set | `{thread_id: heartbeat_ts}` — beat recovery |
| `tokens:{thread_id}` | Stream | SSE token events (`perf_token_batch`, `perf_ingest_progress`, `perf_concurrent_status`) |
| `fin:query:phase:{thread_id}` | String | Current phase for late-connect replay |

## SSE events emitted

| Event | Transport | When | Payload |
|---|---|---|---|
| `perf_ingest_progress` | Redis stream (`stream_token`) | ~every 1 s during ingest (both phases) | `produced, total_tokens, elapsed_ms, ingest_tps, status` |
| `perf_ingest_half_complete` | pg_notify | Phase 1 done | `ingest_ms, produced` |
| `perf_concurrent_status` | Redis stream (`stream_token`) | Every 3 s during Phase 2 | `batch_size, digest_tps, ingest_tps, stream_len` |
| `perf_token_batch` | Redis stream | Batches of 1,000 tokens | `count, task_id, node_name, task_key` |
| `perf_test_complete` | pg_notify | All tokens published | `total_tokens, tps` |
| `perf_test_stopped` | pg_notify | Timeout fired | `duration_secs` |

## perf_test_complete vs perf_test_stopped

| Event | When | Frontend effect |
|---|---|---|
| `perf_test_complete` | `final_stop == "completed"` | Closes that session as "completed" |
| `perf_test_stopped` | `final_stop == "timeout"` | Freezes ALL sessions |

`done` always follows and is a no-op for already-closed sessions.

## _ConcurrentProgress shared state

```python
@dataclasses.dataclass
class _ConcurrentProgress:
    ingest_tps: float = 0.0   # rolling 1-s ingest rate; 0 when ingest done
    ingest_done: bool = False  # True after sentinel is appended
    produced: int = 0          # total tokens produced (both halves)
```

Both coroutines share the same Python object in the same asyncio event loop — no locking needed.

## Frontend — StreamingPerfTestPanel

Location: `frontend/src/components/StreamingPerfTestPanel/` (directory with multiple files).

### Auto-fanout on mount (5 sessions)

```tsx
// In useEffect([])
openSessionStream(initialThreadId);   // session 1 (pre-created by App.tsx)
// Sessions 2-5: submitQuery → openSessionStream in parallel
const label = `Stream #${labelCounter.current++}`;  // computed OUTSIDE setSessions
setSessions((prev) => [...prev, { thread_id, label, ... }]);
openSessionStream(thread_id);
```

**React StrictMode guard (`didSpawnRef`)** prevents the double-mount from firing 4 extra backend requests.

**Label counter**: `useRef` — persists across remounts. Always computed outside `setSessions` updaters.

### `openStream` intentional-close contract

Cleanup returned by `openStream` sets `closed = true` and calls `es.close()` **without** calling `notifyClose()`. `onClose` only fires on genuine unexpected drops (`es.onerror` with `CLOSED` readyState).

### Safety timeout in `attachStream`

```ts
const tid = setTimeout(() => {
  cancelQuery(thread_id, "timeout").catch(() => {});
}, config.timeoutSecs * 1000);
```

Fires only on silent network partition. Normal event flow cancels it via `closeSession → clearTimeout`.

### New event handlers in `useBrowserStreamSession`

| Handler | Event | Action |
|---|---|---|
| `onPerfIngestHalfComplete` | `perf_ingest_half_complete` | Sets `ingest_status: "running"` (second half still going) and `ingest_ms` |
| `onPerfConcurrentStatus` | `perf_concurrent_status` | Updates `concurrent_batch_size`, `concurrent_digest_tps`, `concurrent_ingest_tps`, `concurrent_stream_len` |
| `onCompleted` (`mock_ingest`) | `completed` | Sets `pub_start_ms` only (ingest still running for second half) |

### Table columns

| Column | Description |
|---|---|
| Stream | Label (Stream #1 …) |
| Status | Connecting / Received / Preparing / Ingesting / Sending / Completed / Failed / Cancelled |
| Tokens | Accumulated count from `perf_token_batch` events |
| Ingest | `produced / total` with TPS badge |
| Ingest Time | First-half ingest wall-clock from `perf_ingest_half_complete` |
| **Concurrent** | `batch_size` + `digest_tps ↓ / ingest_tps ↑`; tooltip shows ratio and backlog |
| Progress | `tokens / total_tokens` % |
| Token Rate | Live TPS |
| Digest Time | Pub-phase wall-clock |
| Thread ID | Truncated UUID |
| Action | Per-row Stop |

### Dashboard stats

Total Tokens · Active Streams · Completed · Avg Token Rate · Tokens/sec (last 1 s) · Peak tps

## Key files

| File | Role |
|---|---|
| `backend/graph/builder.py` | `PERF_TEST_TRIGGER` + `build_unified_graph()` |
| `backend/graph/state.py` | `PerfTestState` |
| `backend/graph/runner.py` | `run_graph_task` Celery task; emits `preparing`; deletes phase on finish |
| `backend/graph/agents/perf_test/node.py` | Two-phase concurrent node |
| `backend/graph/agents/perf_test/tasks/fanout_to_streams.py` | `_ConcurrentProgress`, `run_ingest_first_half`, `run_ingest_second_half`, `dynamic_reader_gen` |
| `backend/graph/agents/perf_test/celery_ingest/celery_app.py` | `perf_ingest_app` |
| `backend/graph/agents/perf_test/celery_ingest/config.py` | DB indices, key prefixes, batch sizes |
| `backend/graph/agents/perf_test/celery_ingest/tasks.py` | `bulk_ingest_stream` + `recover_stalled_streams` |
| `backend/graph/agents/task_keys.py` | `PERF_TEST_INGEST`, `PERF_TEST_PUB` |
| `backend/sse_notifications/agent_tasks/token_stream.py` | `stream_perf_text_task()` — batched `perf_token_batch` |
| `backend/db/redis/query_phase.py` | `set/get/delete_query_phase` |
| `backend/sse_notifications/perf_test/notifications.py` | `emit_perf_ingest_half_complete`, `emit_perf_test_complete`, etc. |
| `backend/api/queries.py` | `apply_async` dispatch; emits `received` phase |
| `backend/api/stream.py` | SSE gateway; forwards `perf_token_batch` bypassing watch registry |
| `frontend/src/api/stream.ts` | `openStream` with `onPerfTokenBatch`, `onPerfIngestHalfComplete`, `onPerfConcurrentStatus`, etc. |
| `frontend/src/components/StreamingPerfTestPanel/usePerfSession.ts` | SSE stream lifecycle hook |
| `frontend/src/components/StreamingPerfTestPanel/types.ts` | `ThreadSession` with `concurrent_*` fields |


The SSE stream produced is structurally identical to a real LLM run. The frontend
processes it with the same `onStarted` / `onToken` / `onDone` handlers.

## Frontend StreamingPerfTestPanel (`frontend/src/components/StreamingPerfTestPanel.tsx`)

### Props

```ts
interface StreamingPerfTestPanelProps {
  initialThreadId: string;   // first thread_id submitted by App
  userToken: string;         // for spawning additional requests
  initialCleanup: () => void; // App hands over SSE cleanup ownership
}
```

### Features

- **Interactive grid** (`antd Table`) — one row per concurrent stream:
  - Status badge, token count, % of total, token rate (tps), elapsed duration, thread ID (truncated)
  - Per-row **Stop** button
- **Aggregate statistics** (`antd Statistic`): total tokens, active streams, completed count, avg token rate
- **Add Request** button — calls `submitQuery("DO STREAMING PERFORMANCE TEST NOW")` then `openStream`, adds a new row
- **Stop All** button — closes all active SSE connections
- Auto-stop: each session cancels itself after 5 minutes via `setTimeout`
- Live refresh: `setInterval(1 s)` ticks while any session is active to keep rate/duration columns current

### Session lifecycle

```
submitQuery → openStream → onToken (increment counter) → onDone / timeout → closeSession
```

`closeSession` cancels the SSE `EventSource`, clears the 5-min timeout, and marks
the row with a final status (`stopped` / `completed` / `failed` / `cancelled`).

### App.tsx integration

```tsx
// In handleSubmit — detect trigger before normal flow
if (query.trim() === PERF_TEST_TRIGGER) {   // "DO STREAMING PERFORMANCE TEST NOW"
  const res = await submitQuery(query, userToken!);
  setPerfTestThreadId(res.thread_id);
  return;
}

// In <Content>
{perfTestThreadId ? (
  <StreamingPerfTestPanel key={perfTestThreadId} initialThreadId={perfTestThreadId} userToken={userToken!} initialCleanup={() => {}} />
) : (
  <MessageList ... />
)}
```

## SSE stream timing logs (`backend/api/stream.py`)

| Log key | Level | When |
|---|---|---|
| `[stream] first_token_forwarded wait_ms=...` | DEBUG | First token forwarded to client |
| `[stream] tokens_forwarded=... suppressed=... tps=...` | DEBUG | Every 200 forwarded tokens |
| `[stream] done tokens_forwarded=... suppressed=... elapsed=...s` | INFO | `done` event sent |

## Redis publish timing logs (`backend/graph/utils/task_stream.py`)

| Log key | Level | When |
|---|---|---|
| `[task_stream] slow_publish pub_ms=... token#=...` | WARNING | Single Redis publish >20 ms |
| `[task_stream] publish_stats tokens=... avg_pub_ms=... tps=...` | DEBUG | Every 200 tokens |
| `[task_stream] stream_text_task finished tokens=... avg_pub_ms=... tps=...` | DEBUG | Stream end |

## Key files

| File | Role |
|---|---|
| `backend/llm/providers/mock.py` | `MockChatModel` — async token generator |
| `backend/api/queries.py` | `_STREAMING_PERF_TEST_TRIGGER` detection + routing |
| `frontend/src/components/StreamingPerfTestPanel.tsx` | Interactive grid component |
