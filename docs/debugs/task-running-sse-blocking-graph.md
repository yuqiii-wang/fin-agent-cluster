# Debug: `task:running` SSE blocking graph progress when UI disconnects

**Date:** 2026-05-27  
**Symptom:** Node `48decf86-4fb2-5d57-93d2-fedfd48909c2` completed all tasks but appeared stuck for ~90 seconds before the next node started.

## Root Cause

The task `notify` function (`centrifugo_mq/sse_notification/thread/node/task/notify.py`) had **no `require_ack` parameter** — it always blocked waiting for a frontend ACK when `has_thread_viewers` returned True, regardless of event type.

This caused `task:running` (informational, fire-and-forget) to block `create_task` for up to 30 s per task when the UI was not actively ACK'ing. This is inconsistent with node `notify`, which already uses `require_ack=(status != "running")`.

## Log Evidence

```
# UI viewer registered at 14:29:50, last Centrifugo token at 14:30:26
# ~2.5 minute UI silence while tasks were running

14:30:20 — task:4cbcd90b:running   NACK/exhausted  total_ms=30082
14:30:36 — thread:stream_start     NACK/exhausted  total_ms=15184
14:31:14 — task:4cbcd90b:completed NACK/exhausted  total_ms=30193
14:31:45 — task:d14dc6b0:running   NACK/exhausted  total_ms=30204
14:32:26 — task:d14dc6b0:completed NACK/exhausted  total_ms=30203
14:32:57 — task:9205e8d5:running   NACK/exhausted  total_ms=30119
              (UI reconnected at 14:33:05 — too late in retry window)
14:33:28 — task:9205e8d5:completed NACK/exhausted  total_ms=30153
14:33:58 — node:48decf86:completed NACK/exhausted  total_ms=30052
              (LangGraph proceeds to next node immediately after)
14:34:29 — next node: 9 tasks all :running NACK/exhausted  total_ms=~30s
```

## Why `has_thread_viewers` stayed True

The viewer Redis key has a 30-minute TTL (`viewer_store.py`). The UI PUT the viewer at 14:29:50 but its Centrifugo connection dropped ~14:30:26 without DELETing the viewer. The stale Redis flag caused `has_thread_viewers → True`, so all notify calls entered the full retry loop.

## Fix

Added `require_ack: bool = True` parameter to task `notify` (matching node `notify`), and updated `emit_task_sse` to pass `require_ack=(status != "running")` so `task:running` events are published once and return immediately — they are informational and do not need to block the graph.

Files changed:
- `backend/centrifugo_mq/sse_notification/thread/node/task/notify.py`
- `backend/langgraph/lifecycle/threads/nodes/tasks/sse.py`

## Impact

Before fix: each `task:running` blocked `create_task` for up to 30 s → for a node with N tasks the cumulative stall could be N × 30 s just for task creation, before celery even ran.

After fix: `task:running` is fire-and-forget; only `task:completed` and `task:failed` wait for ACK (same policy as node events).
