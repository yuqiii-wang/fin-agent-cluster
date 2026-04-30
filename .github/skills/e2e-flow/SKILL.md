---
name: E2E Flow
description: Overview of the end-to-end flow for the fin-trading-cluster skill, covering FastAPI instances, Redis Streams, Centrifugo setup, request lifecycle, graph execution, and key events.
---
# E2E Flow Skill — fin-trading-cluster

## Two Flows — Never Mix

| Flow | Transport | Use case |
|------|-----------|----------|
| **Streaming** | Redis Streams + Centrifugo WebSocket | LLM tokens, lifecycle events, perf-test |
| **Non-streaming** | REST | Query submit, control, config |

**Token path**: Celery `llm_ingest` → `fin:llm:tokens` (Redis Stream) → Centrifugo native consumer → browser. FastAPI not involved.  
**Lifecycle path**: FastAPI → `publish_lifecycle()` → `publish_to_channel()` → Centrifugo HTTP API → browser.

---

## FastAPI Instances

| Type | Count | Ports | Module | Notes |
|------|-------|-------|--------|-------|
| Runner | 4 | 8432–8435 | `backend.main:app` | LangGraph + Celery + reads |
| Assistant | 2 | 8436–8437 | `backend.assistant.main:app` | No LangGraph/Celery |

Kong: `POST /users/query` + `/ack` → `runner-upstream`; all else → `assistant-upstream`.

---

## Redis Streams

| Stream | Writer | Reader | Deletion |
|--------|--------|--------|----------|
| `fin:llm:tokens` | Celery `llm_ingest` (per token, shard-routed) | Centrifugo XREADGROUP+XACK | Never (MAXLEN~) |
| `fin:llm:completions` | Celery `llm_ingest` (1/LLM call, shard 0) | Celery `pg_persist` beat | After PG INSERT (XACK+XDEL) |
| `fin:perf:{thread_id}` | ingest tasks | `dynamic_reader_gen()` | Internal only |

Celery workers: `llm_ingest` (on-demand), `pg_persist` (beat every 10s) — both on `stream:ingest` queue.

---

## Centrifugo

- 2 nodes: `centrifugo-0` (redis-0, port 8101), `centrifugo-1` (redis-1, port 8102)
- Shard: `SHA-256(thread_id) % 2` — same in `get_shard_index()` and `RedisRouter._shard_index()`
- Channel: `thread:{thread_id}` — carries ALL events; namespace `thread`: `history_size=500`, `history_ttl=600s`, `force_recovery=true`
- Auth: HS256 JWT (`CENTRIFUGO_TOKEN_HMAC_SECRET_KEY`); connection token + subscription token
- Token endpoint: `GET /api/v1/centrifugo/token?thread_id=` → `{ws_url, connection_token, subscription_token, shard_index, channel}`
- Publish: `POST http://centrifugo-{n}:8000/api` with `apikey` header — only for lifecycle events
- Token stream entry format (Centrifugo v6): `{"method":"publish","payload":"{\"channel\":\"thread:{id}\",\"data\":{\"event\":\"token\",...}}"}`

---

## Request Lifecycle

### 1. Submit `POST /api/v1/users/query`
`backend/api/queries.py` → dedup guard → INSERT `user_queries` (status=`received`) → `set_query_phase("received")` → `emit_query_status("received")` (records in `query_status_ack:{thread_id}`) + `emit_query_received` → return `{thread_id, status:"received"}`.  
**Frontend**: immediately sets session status to `"received"` from the HTTP response (no need to wait for Centrifugo event). Graph not started yet.

### 2. WebSocket Subscribe
Frontend: `fetchCentrifugoToken(thread_id)` → `Centrifuge(ws_url)` → `newSubscription(channel, {recoverable:true, since:{epoch:'',offset:0}})` → `sub.on("publication", ctx => dispatch(ctx.data, handlers))`.  
`since:{epoch:'',offset:0}` forces full history replay, covering events published before WS connected.

### 3. ACK `POST /api/v1/users/query/{thread_id}/ack`
`ack_query()`: `SELECT FOR UPDATE` (dedup) → UPDATE status=`running` → `asyncio.create_task(run_graph_async(...))` → `mark_task_active()` → `emit_query_ack_confirmed`.

### 4. Query-Status ACK Handshake
- Backend `emit_query_status(thread_id, phase)` → publishes `query_status` event AND records in `query_status_ack:{thread_id}` hash as `is_ack=False`.
- Frontend `onQueryStatus` handler → updates status (received/preparing) → `POST /api/v1/stream/{thread_id}/status-ack` with `{phase, is_double_check?}` → assistant marks `is_ack=True`.
- Assistant status-verifier (background task, `backend/assistant/status_verifier.py`) runs every `STATUS_VERIFIER_INTERVAL_SECS` (default 30s): queries DB for active queries, checks unACKed phases in Redis, re-publishes via Centrifugo **with `is_double_check: True`** in the event payload.
- On the **2nd+ delivery** (`is_double_check=True`): frontend adds `X-Double-Check: true` header to the ACK request; Kong route `route-stream-double-check` (header-matched, higher specificity) pins these to `fastapi-assistant` upstream.

---

## Graph Execution (`backend/graph/runner.py`)

```
run_graph_async(thread_id, query)
  → set_query_phase("preparing") + emit_query_status
  → graph.ainvoke()
      ├─ perf-test (query == "DO STREAMING PERFORMANCE TEST NOW"):  stream_runner → Celery ingest → Centrifugo
      └─ fin-analyst (all other queries):  fin_analyst_runner (stub — lifecycle events only)
  → _running_tasks.pop(thread_id)      ← sync, before any await
  → UPDATE status='completed' WHERE status='running'  ← atomic ownership claim
  → if claimed: emit_done() + cleanup_thread_session()
```

**Ownership**: runner or cancel — whichever gets 0 rows from the UPDATE is the loser.

---

## Fin-Analysis Node Pattern

Each node: `create_task()` (DB INSERT + emit `started`) → `dispatch_llm()` (Celery tokens) → `_check_signal()` (cancel check) → `complete_task()` (DB UPDATE + emit `completed`).

Nodes: `query_optimizer` → `market_data_collector` (per sub-task) → `decision_maker`.

---

## Perf-Test Pipeline

**Throughput**: ingest 95% → `perf_test_ingest` task complete → ingest last 5% + `stream_perf_text_task` (XREAD `fin:perf:{thread_id}` → `perf_token_batch` → Centrifugo) in parallel.

**Concurrency**: Priority-scheduled slice dispatch — a FastAPI async coordinator dispatches short `run_stream_ingest_slice` tasks (2s each) to Celery workers. Multiple streams share the worker pool via time-slicing, ensuring all streams (even > worker count) receive tokens.

**Concurrency scheduler flow**:
1. Each stream calls `dispatch_scheduled_ingest(run_id, ...)` — registers in `fin:stream:sched:state:{run_id}:{stream_id}` (shard 0).
2. First registrant wins coordinator lock (`SETNX fin:stream:sched:coord:{run_id}`).
3. Coordinator (`_run_scheduler_coordinator`) waits 500ms rendezvous then loops every 250ms:
   - Reads all states (pipeline batch).
   - Detects `done=1` streams → pushes result to `fin:stream:ingest:done:{stream_id}` (stream's shard).
   - Scores active non-inflight streams: `produced==0 → -inf`, `produced>0 → exp(shard_pending / 5000)`.
   - Dispatches top-priority slices up to `MAX_INFLIGHT=8`.
4. `run_stream_ingest_slice` runs ingest for `slice_secs`, updates progress, sets `done=1` on terminal stop, clears inflight flag.
5. FastAPI dispatcher BLPOPs `done_key` and returns `(produced, stop_reason, ingest_ms)`.

---

## Key Redis Keys

| Key | Type | Writer | Reader |
|-----|------|--------|--------|
| `fin:llm:tokens` | Stream | Celery ingest/slice tasks | Centrifugo consumer |
| `fin:llm:completions` | Stream | Celery `llm_ingest` | Celery `pg_persist` |
| `fin:perf:{thread_id}` | Stream | ingest tasks | `dynamic_reader_gen` |
| `fin:stream:sched:state:{run_id}:{stream_id}` | Hash (shard 0) | `register_stream`, slice task | coordinator |
| `fin:stream:sched:inflight:{run_id}:{stream_id}` | String TTL (shard 0) | `mark_stream_inflight` | coordinator batch check |
| `fin:stream:sched:coord:{run_id}` | String TTL (shard 0) | `try_become_coordinator` | coordinator (SETNX) |
| `fin:stream:sched:streams:{run_id}` | Set (shard 0) | `register_stream` | coordinator |
| `fin:stream:ingest:done:{stream_id}` | List (thread shard) | coordinator `_push_final_result` | FastAPI BLPOP |
| `task_active:{thread_id}` | String TTL 1h | `mark_task_active()` | `is_task_active_any_instance()` |
| `query_phase:{thread_id}` | String | `set_query_phase()` | `get_query_phase()` |
| `query_status_ack:{thread_id}` | Hash TTL 30m | `record_query_status_event()` | assistant verifier + `ack_query_status_event()` |

---

## Event Reference (channel `thread:{thread_id}`)

| Event | Source | Frontend |
|-------|--------|----------|
| `query_received` | `emit_query_received()` | `onQueryReceived` → POST /ack |
| `query_ack_confirmed` | `emit_query_ack_confirmed()` | `onQueryAckConfirmed` |
| `query_status` | `emit_query_status()` | `onQueryStatus` → phase label |
| `started` | `create_task()` | `onStarted` |
| `token` | Celery → `fin:llm:tokens` → Centrifugo | `onToken` |
| `perf_token_batch` | `stream_perf_text_task` | `onPerfTokenBatch` |
| `perf_concurrent_status` | `dynamic_reader_gen` | `onPerfConcurrentStatus` |
| `perf_ingest_progress` | `emit_perf_ingest_progress()` | `onPerfIngestProgress` |
| `perf_ingest_complete` | `emit_perf_ingest_complete()` | `onPerfIngestComplete` |
| `completed` | `complete_task()` | `onCompleted` |
| `failed` / `cancelled` | `fail_task()` / `cancel_task()` | `onFailed` / `onCancelled` |
| `perf_test_complete` / `perf_test_stopped` | `emit_perf_test_*()` | `onPerfTest*` |
| `done` | `emit_done()` | `onDone` → close stream |

---

## Kong Routes

| Route | Path | Notes |
|-------|------|-------|
| `route-centrifugo-token` | `/api/v1/centrifugo` | HTTP token endpoint |
| `route-centrifugo-0/1` | `/centrifugo-0/1` | strip_path=true, ws/wss |
| `route-stream-double-check` | `/api/v1/stream` + `X-Double-Check: true` | higher specificity → assistant; for verifier re-delivery ACKs |
| `route-stream-utils` | `/api/v1/stream` | `POST /{id}/done-ack`, `POST /{id}/status-ack` → assistant |

---

## New Feature Checklist

1. **Pick flow**: streaming (Centrifugo WS) or REST — never mix.
2. **Lifecycle event**: `publish_lifecycle(thread_id, payload)` after `session.commit()`.
3. **Token/high-freq**: `stream_token()` → Celery → `fin:llm:tokens` → Centrifugo native consumer.
4. **Frontend**: add `case "my_event":` in `dispatch()` in `frontend/src/api/stream.ts`.
5. **Race**: if event can race with `done`, handle ordering explicitly.
6. **History**: Centrifugo covers last 500 events / 600s — no extra replay logic.
7. **Errors**: add to nearest `errors/codes.py`; log and return to UI.

