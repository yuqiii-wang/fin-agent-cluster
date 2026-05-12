# LLM Stream Delivery Fixes

## Symptom

Queries submitted from the UI show SSE lifecycle events arriving correctly
(node_status, task_status, `done`) and the ACK flow completes normally, but
**no LLM tokens** are ever delivered to the frontend.  The thread view stays
empty after the graph finishes.

In `backend/logs/streaming.log`:

```
[stream_task] completed thread=<uuid> viewers=False
```

The `viewers=False` suffix is the giveaway.  Backend finished the graph run,
persisted the answer to Postgres, but skipped all of:

- `centrifugo-llm` token batch publishing
- `stream_complete` SSE event
- Redis stream recovery entries

## Architecture Background

`stream_task` (Celery worker in `backend/celery_task/workers/tasks/stream_task.py`)
runs the LLM and decides whether to publish tokens based on two viewer checks:

```python
viewers_present = (
    await has_app_viewers(thread_id)   # Is the user's browser open at all?
    and await has_thread_viewers(thread_id)  # Is the user watching this thread?
)
```

If `viewers_present=False` the worker skips publishing entirely to avoid
wasted Centrifugo traffic for background queries (e.g., mobile app closed).

`has_app_viewers` polls the **Centrifugo presence stats** HTTP API on
`centrifugo-sse` for `user:{userId}`.  `has_thread_viewers` polls for
`thread:{threadId}`.  Both require `presence: true` in the centrifugo-sse
namespace config, which is set.

## Root Cause: WebSocket Subscription Timing Race

The check runs approximately **1-2 seconds** after query submission.  During
that window the frontend must:

1. `useCentrifugoPresence` → fetch token → open WS to `centrifugo-sse` →
   subscribe to `user:{userId}` (presence channel).
2. `useCentrifugoSse` → fetch token → open WS to `centrifugo-sse` →
   subscribe to `thread:{threadId}` (presence channel).

Both are async React hooks.  The sequence is:

```
t=0ms   User clicks Submit → HTTP POST /threads/{id}/query
t=~20ms backend: dispatch_graph_run() + set_thread_user() called
t=~50ms Celery worker picks up stream_task
t=~500ms stream_task: calls has_app_viewers() + has_thread_viewers()
         → Centrifugo presence check → 0 clients subscribed → viewers=False
t=~600ms Frontend: WS handshakes complete, subscriptions confirmed
         (too late — stream_task already skipped publishing)
```

The race window is typically 400–800 ms on a local Docker stack.  On first
load or after a tab sleep the WS re-handshake can take 1–2+ seconds, making
the race virtually certain.

## Investigation Steps

1. **Confirm the symptom**: check `backend/logs/streaming.log` for
   `viewers=False` on the affected thread UUID.

2. **Confirm SSE is working**: search the same log for the thread UUID —
   if `task SSE acked` / `node SSE acked` / `thread SSE acked event=done`
   appear but `stream_complete` does not, the SSE path is fine and only
   token publishing was skipped.

3. **Check Centrifugo presence timing**: temporarily add a log before the
   viewer check in `stream_task.py` to print the timestamp delta from the
   task-received time.  Typical value: 400–600 ms.  Confirms race window.

4. **Verify presence is enabled**: `centrifugo-sse-0/config.json` and
   `centrifugo-sse-1/config.json` must have `"presence": true` in the
   `thread` and `user` namespaces.  Missing this causes permanent
   `num_clients=0`.

## Fix: Explicit Redis Viewer Flags (Redis-first, Centrifugo fallback)

### New module: `backend/db/redis/session/viewer_store.py`

Two Redis keys set atomically (pipeline) with a 30-minute TTL:

| Key | Meaning |
|-----|---------|
| `fin:user:app_viewer:{userId}` | User's browser is open |
| `fin:thread:viewer:{threadId}` | User is viewing this thread |

Functions:
- `set_viewer(user_id, thread_id)` — set both keys
- `has_app_viewer(user_id)` — GET the app key
- `has_thread_viewer(thread_id)` — GET the thread key

Uses Redis shard 0 (control plane, same as other session keys).

### `backend/users/queries.py` — set flags at submission time

`submit_query()` calls `await set_viewer(str(user.id), thread_id)` immediately
after `set_thread_user`, **before** `dispatch_graph_run` returns.  The flags
are in Redis before the Celery task even starts, eliminating the race entirely
for new queries.

### `backend/centrifugo_mq/client.py` — Redis-first check

Both `has_app_viewers` and `has_thread_viewers` now follow the pattern:

```python
# 1. Check explicit Redis flag (set at submission — always available in time)
if await has_app_viewer(user_id):
    return True

# 2. Fall back to Centrifugo presence (covers reconnects / new tabs where
#    the Redis flag may pre-date the current session but WS is live)
... presence_stats HTTP call ...
```

The Centrifugo fallback is kept for the case where the user opens the app
in a new tab after a query was already submitted in a previous session and
the Redis flag has since expired (TTL 1800s) but the WebSocket is live.

### `backend/api/threads/router.py` — `PUT /{thread_id}/viewer` endpoint

For **history thread navigation** (user clicks a past thread in the sidebar):
the query was submitted in a previous session so no flags exist.  The new
endpoint sets them when the user navigates to the thread:

```
PUT /api/v1/threads/{threadId}/viewer
Header: X-User-Token: <guest token>
Response: 204 No Content
```

### `frontend/src/api/threads.ts` — `setThreadViewer()`

Fire-and-forget helper that calls the PUT endpoint.  Errors are swallowed
(backend defaults to `True` for viewer detection on any failure path).

### `frontend/src/App.tsx` — call on thread selection

`handleSelectThread(threadId)` calls `setThreadViewer(threadId)` so opening
any thread — whether new or from history — registers the viewer before any
in-flight `stream_task` checks.

## Coverage Matrix

| Scenario | Before fix | After fix |
|----------|-----------|-----------|
| New query, fast WS | Works (race window barely missed) | Works (Redis flag pre-set) |
| New query, slow WS (first load) | `viewers=False` — tokens lost | Works (Redis flag pre-set) |
| History thread navigation to running query | `viewers=False` | Works (PUT /viewer called) |
| Background query (app closed) | Correctly skips | Correctly skips (no Redis flag, no Centrifugo clients) |
| Reconnect in new tab | Works (Centrifugo fallback) | Works (Centrifugo fallback) |

## Files Changed

- `backend/db/redis/session/viewer_store.py` — new
- `backend/db/redis/session/__init__.py` — exports new functions
- `backend/users/queries.py` — `set_viewer` call at submission
- `backend/centrifugo_mq/client.py` — Redis-first viewer checks
- `backend/api/threads/router.py` — `PUT /{thread_id}/viewer` endpoint
- `frontend/src/api/threads.ts` — `setThreadViewer()` helper
- `frontend/src/App.tsx` — `handleSelectThread` calls `setThreadViewer`

---

## Follow-up: ConcurrencyTest Grid Regressions (same session)

After the above fix was merged, the ConcurrencyTest grid showed further
problems: thread status stuck at "pending", ACK% < 100%, and 0 tokens for
some threads.  The following sub-issues were identified and fixed.

---

### Sub-issue 1: viewer_store error default returned `False`

`has_app_viewer` / `has_thread_viewer` originally returned `False` on any
Redis exception.  When Celery `asyncio.run()` creates a new event loop per
task, `get_client` detects the loop-id mismatch, acquires a lock, and
recreates the `aioredis` pool.  Under 5 concurrent tasks on the same worker
process, this first `GET` on a fresh pool can transiently raise
`ConnectionError` or `TimeoutError`.  Old `False` return bypassed the
Centrifugo fallback entirely → `viewers_present = False` → 0 tokens.

**Fix**: both functions return `True` on error — safe default because callers
treat `True` as "a viewer exists, publish streaming."

---

### Sub-issue 2: ACK% < 100% — SSE disconnect race on `done`

When `done` arrived, `status: 'completed'` was set synchronously.  This
triggered React re-render → `isThreadTerminal(status) = true` → `done=true`
→ SSE `useEffect` cleanup → **disconnect**.  `ack_confirmed` events in flight
for the last 2–3 events (task_status:completed, node_status:completed, `done`
itself — all with ~20–50 ms round-trip) arrived **after** disconnect → never
counted → ACK% < 100%.

**Fix: ACK drain mechanism** in `useConcurrencyThread.ts`.

`done` / `thread_failed` / `thread_status:cancelled` no longer call
`onUpdate` directly.  Instead they set two refs:

```typescript
wantsCloseRef.current = true;
terminalStatusRef.current = 'completed'; // TerminalQueryStatus
checkDrain();
```

`checkDrain()` only sets the terminal status (closing the SSE connection)
when `sentAckKeysRef.size ≤ countedConfirmedKeysRef.size` — every sent ACK
has been confirmed.  It is called:
1. Immediately after flagging wantsClose (handles history-replay fast path
   where all confirmations already arrived).
2. After each `ack_confirmed` is counted (catches the last in-flight
   confirmation for the live path).
3. After each ACK RPC is registered (covers the case where confirmation
   already arrived before we sent).

The SSE connection stays alive until the drain completes, then sets terminal
status → `done=true` → cleanup.

---

### Sub-issue 3: Thread Status stuck at "pending"

Two causes:

**Cause A** — `ConcurrencyTest.tsx` hardcoded `status: 'pending'` ignoring
`r.status` from the API response (which is `'received'`).  Fixed by using
`r.status as QueryStatusValue` for initial row state.

**Cause B** — The backend emits no `thread_status: running` SSE event.
Fixed by inferring thread `'running'` status from the first
`node_status: running` or `task_status: running` SSE event.
`thread_status: cancelled` was also unhandled — added to the drain path.

---

### Sub-issue 4: 0 LLM tokens for some threads — LLM subscription gated on `done`

With SSE `since: { offset: 0, epoch: '' }` (history recovery from offset 0),
the full SSE event history replays in a single microtask burst on connection.
If all events + `ack_confirmed` replayed before the LLM `useEffect` ran, the
drain resolved immediately → `status: 'completed'` set → `done=true` →
the LLM `useEffect` guard `if (!llmInfo || done) return` skipped → **LLM
subscription never established**.

**Fix**: removed `done` from the LLM `useEffect` guard and dependency array.
The LLM subscription is established unconditionally whenever `llmInfo` is
available, regardless of drain state.  Added `since: { offset: 0, epoch: '' }`
to the LLM subscription for history recovery of tokens published before the
WebSocket connected.  Disconnection happens only on component unmount (user
leaves the thread), not on `stream_end`.

---

### Sub-issue 5: Inline status literals — replaced with lifecycle constants

`terminalStatusRef` was typed `'completed' | 'failed' | 'cancelled' | null`
inline.  `streamTaskStatus` guard used an inline string list.
Active-thread filter in the aggregation row compared literal strings.

**Fix**: added `QueryStatusValue`, `TerminalQueryStatus`, and `WorkStatusValue`
types to `frontend/src/constants/lifecycleStatus.ts`.  All three files now
import from that single source of truth.

---

### Sub-issue 6: No visibility into LLM MQ connection state

Added `llmMqConnected: boolean` to `ThreadRow`.  The LLM Centrifugo
subscription emits `llmMqConnected: true` on `subscribed` and `false` on
`unsubscribed`.  A new **MQ** column under **LLM Streaming** in the grid
shows a green `●On` / gray `●Off` badge so operators can immediately see
which threads have an active LLM channel.

---

### Files Also Changed (follow-up)

- `backend/db/redis/session/viewer_store.py` — `has_*` return `True` on error
- `frontend/src/constants/lifecycleStatus.ts` — `QueryStatusValue`, `TerminalQueryStatus`, `WorkStatusValue` types
- `frontend/src/components/ConcurrencyTest/types.ts` — `status` / `streamTaskStatus` use imported types; `llmMqConnected` field
- `frontend/src/components/ConcurrencyTest/useConcurrencyThread.ts` — ACK drain, `TerminalQueryStatus` import, LLM subscription decoupled from `done`, `llmMqConnected` tracking, `isWorkActive`/`isWorkTerminal` guards
- `frontend/src/components/ConcurrencyTest/ConcurrencyTest.tsx` — initial `status` from API response, `isThreadActive` for agg filter, **MQ** column

---

## Sub-issue 7: 0 Tokens for Fast-Completing Threads — Centrifugo Epoch Mismatch

### Symptom

In a 5-thread concurrency test, one thread shows:
- `Latency to Conclusion`: 2.2 s (much faster than the other 4 at ~20 s)
- `MQ`: On (LLM subscription connected)
- `TPS`: — (zero, never set)
- `Tokens`: 0 / 0

All other threads stream normally.  Backend log confirms `viewers=True` and
`tokens=303 latency_ms=9970` for the fast thread — tokens were published.

### Root Cause: `since: { epoch: '' }` mismatch on a non-empty channel

`useConcurrencyThread.ts` subscribed to the LLM channel with:

```typescript
const sub = cf.newSubscription(llmInfo.channel, {
  token: llmInfo.subscription_token,
  since: { offset: 0, epoch: '' },
});
```

The intent was to recover missed history.  However, Centrifugo uses an opaque
epoch string to identify a channel's publication log.  A new channel starts
with `epoch = ''`.  The first `XADD` entry to `fin:llm:tokens` for that
thread causes Centrifugo to assign a non-empty epoch (e.g. `'E1a7f...'`).

When the subscription connects and sends `since: { offset: 0, epoch: '' }`:

- **Slow threads (normal case)**: the WS connects before the Celery worker
  starts streaming, so the channel is still empty (`epoch = ''`).
  `'' == ''` → `recovered: true` → live tokens arrive normally.
- **Fast thread**: research nodes completed in ~0.8 s; `stream_task` began
  before the LLM subscription was established.  By the time the WS connected
  the channel had 100+ tokens and a real epoch.  `'' ≠ 'E1a7f...'` →
  `recovered: false` → history not replayed and Centrifugo marks the
  subscriber at the current tail → **all 303 tokens invisible**.

### Why one thread was fast

5 threads submitted in parallel via `Promise.all`.  All 5 hit the Celery
on-demand queue simultaneously.  Thread `f7b5c955` was scheduled first and
got exclusive access to the workers through all four stages (analyze_query,
read_news, read_stats, merge_results, stream_conclusion).  The other 4 queued
behind it, adding ~18 s of latency before their own `stream_task` started.

### Investigation

Check logs for the affected thread:

```
grep f7b5c955 logs/db.log | grep "first xadd"
# → 2026-05-12T08:27:29.013928 — tokens published at T+2.2s

grep f7b5c955 logs/centrifugo.log | grep "conclusion_node:running"
# → 2026-05-12T08:27:28.951773 — conclusion_node started at T+2s
```

The LLM subscription WS handshake completes well after T+2s on the browser
side → epoch mismatch guaranteed for the fast thread.

### Fix

**Backend** — `centrifugo-llm-0/config.json` and `centrifugo-llm-1/config.json`:
set `"force_recovery": true` in the `thread` namespace.  Centrifugo now
automatically delivers full channel history to every new subscriber on connect,
regardless of what `since` the client sends.

**Frontend** — `frontend/src/components/ConcurrencyTest/useConcurrencyThread.ts`:
removed `since: { offset: 0, epoch: '' }` from the LLM subscription.  With
`force_recovery: true` the server pushes history automatically; a blank
`epoch` from the client would be ignored anyway, but omitting it avoids
confusion and future Centrifugo version surprises.

```typescript
// Before
const sub = cf.newSubscription(llmInfo.channel, {
  token: llmInfo.subscription_token,
  since: { offset: 0, epoch: '' },   // ← epoch mismatch on non-empty channel
});

// After
const sub = cf.newSubscription(llmInfo.channel, {
  token: llmInfo.subscription_token, // force_recovery delivers history automatically
});
```

Note: the SSE channel subscription in the same file retains
`since: { offset: 0, epoch: '' }` because `centrifugo-sse` channels use
per-user `user:` and `thread:` namespaces that are opened fresh per query —
the epoch race does not apply there.  The LLM channel is the only one where
a fast backend can pre-populate the channel before the WS connects.

### Centrifugo containers must be restarted after the config change.

### Files Changed

- `centrifugo/centrifugo-llm-0/config.json` — `force_recovery: false` → `true`
- `centrifugo/centrifugo-llm-1/config.json` — `force_recovery: false` → `true`
- `frontend/src/components/ConcurrencyTest/useConcurrencyThread.ts` — removed `since` from LLM subscription
