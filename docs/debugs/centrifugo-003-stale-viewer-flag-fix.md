# CENTRIFUGO_003 — Stale Viewer Flag Triggers ACK Retry Loop

## Symptom

```
ERROR [CENTRIFUGO_003] thread event NACK/exhausted
  thread_id=2692ad8f-a1a5-4b30-b7d8-055978293be9  event=stream_start
  ack_key=stream_start:6527a3ca-9976-48e3-8e5f-933aabb0359b:e0c0870d
  total_ms=15105

ERROR [CENTRIFUGO_004] stream_start NACK
  thread_id=2692ad8f-a1a5-4b30-b7d8-055978293be9
  task_id=6527a3ca-9976-48e3-8e5f-933aabb0359b
```

The error cascaded across ALL events for the thread (task_status running/completed,
node_status, stream_start, thread_status), not just `stream_start`.

## Root Cause

The viewer flag (`fin:thread:viewer:{thread_id}`, 30-min TTL) was set at thread
submission time and never cleared when the frontend Centrifugo WebSocket
disconnected.

**Triggering scenario**:
1. User submits a thread → viewer flags set with 30-min TTL.
2. Thread completes → frontend `useCentrifugoSse` tears down (`done=true`).
   Viewer flag **remains in Redis** for up to 30 minutes.
3. User triggers **re-explore** (or opens the thread from history while it's
   still running after a page refresh).
4. Backend starts executing the new/resumed run.
5. `has_thread_viewers(thread_id)` → **True** (stale flag from step 2).
6. Backend enters the **full ACK retry loop** (6 × 5 s = 30 s per event).
7. Frontend Centrifugo subscription is **not yet established** — the WebSocket
   handshake only begins after React renders the new running state.
8. Every event exhausts all retries → CENTRIFUGO_003 storm.

The `total_ms=15105` (3 × 5 s) on `stream_start` and `total_ms=30xxx` (6 × 5 s)
on task/node events confirmed that no ACK arrived in any retry window.

## Evidence

Access log for the affected thread showed a 3-minute gap between the frontend
opening the thread (REST fetches only) and the Centrifugo token fetch:

```
09:08:46  GET /threads/b3c8c788…          # opened from history / post-complete
09:08:46  GET /threads/b3c8c788…/tasks
09:08:46  GET /threads/b3c8c788…/nodes
           — no PUT /viewer, no centrifugo token fetch —
09:09:16  ERROR [CENTRIFUGO_003] first NACK fires (30 s expiry)
           … cascade of NACKs …
09:12:06  PUT /threads/b3c8c788…/viewer   # frontend finally reconnected
09:12:06  GET /auth/centrifugo/sse-notification
09:12:06  GET /auth/centrifugo/llm-token
```

## Fix

**Viewer flag now mirrors the actual WebSocket subscription lifetime.**

### Backend

* `backend/db/redis/session/viewer_store.py` — added `clear_viewer(user_id, thread_id)`
  that DELETEs both Redis keys (app-level + thread-level) in one pipeline call.
* `backend/db/redis/session/__init__.py` — exported `clear_viewer`.
* `backend/api/threads/router.py` — added `DELETE /{thread_id}/viewer` endpoint
  that calls `clear_viewer`.

### Frontend

* `frontend/src/hooks/useCentrifugoSse.ts`:
  - Calls `setThreadViewer(threadId)` inside the microtask, just before
    `cf.connect()`, so the flag is set exactly when the WebSocket opens.
  - Calls `clearThreadViewer(threadId)` at the top of the cleanup function,
    before draining pending ACK promises.

* `frontend/src/api/threads.ts` — added `clearThreadViewer(threadId)` which
  sends `DELETE /api/v1/threads/{threadId}/viewer`.

* `frontend/src/App.tsx` — removed the premature `setThreadViewer(threadId)`
  call from `handleSelectThread`.  It was called before any Centrifugo
  connection, defeating the purpose of the explicit flag.

## New Lifecycle

```
useCentrifugoSse mounts (sseInfo set, done=false)
  └─ microtask fires
       ├─ setThreadViewer(threadId)   ← flag ON
       ├─ cf.connect()
       └─ sub.subscribe()

useCentrifugoSse cleanup (done=true, sseInfo changes, or threadId changes)
  ├─ clearThreadViewer(threadId)      ← flag OFF
  ├─ drain pending ACK promises
  ├─ sub.unsubscribe()
  └─ cf.disconnect()
```

With this change:
- During re-explore gap: flag is OFF → backend publishes once to Centrifugo
  history (no ACK loop), `force_recovery: true` delivers it when frontend
  reconnects.
- While frontend is connected: flag is ON → full ACK loop works correctly.
- After disconnect: flag is OFF immediately → no 30-min stale window.
