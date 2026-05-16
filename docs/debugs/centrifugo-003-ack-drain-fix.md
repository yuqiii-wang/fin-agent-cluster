# CENTRIFUGO_003 — SSE ACK exhausted on thread completion

## Symptom

```
ERROR [CENTRIFUGO_003] node event NACK/exhausted
  thread_id=...  node_id=...  event=node_status  ack_key=node:...:completed:...
  total_ms=30223
```

Backend retried the event 6 × 5 s = 30 s without ever receiving an ACK.

## Root Cause

Race condition between ACK publish and React effect cleanup:

1. The final node of a run emits `node_status: completed` via Centrifugo.
2. The frontend's `sub.on('publication')` handler fires:
   - Calls `onEvent(ev)` → `handleSseEvent` → `refresh()` (async REST call).
   - Starts `sub.publish({ event: 'ack', ack_key, ... })` — returns a pending Promise.
3. `refresh()` returns with `thread.status = completed`.
4. React re-renders: `isDone = true` → `useCentrifugoSse` effect cleanup fires.
5. **Cleanup called `subRef.current.unsubscribe()` and `cfRef.current.disconnect()`
   synchronously** — before the `sub.publish()` round-trip completed.
6. `sub.publish()` rejected with **code 11** ("connection closed") — silently ignored.
7. The ACK was never pushed to Redis. Backend exhausted retries → `CENTRIFUGO_003`.

The `has_thread_viewers()` check returns `True` (Redis flag TTL = 1800 s, nowhere
near expired), so the full ACK retry loop ran every time.

## Fix

`frontend/src/hooks/useCentrifugoSse.ts`

Added `pendingAckPromsRef` — a `Set<Promise<void>>` that tracks every in-flight
`sub.publish()` ACK promise.

**Publication handler** (after starting the ACK):
```ts
if (!cancelled) {
  pendingAckPromsRef.current.add(ackProm);
  ackProm.finally(() => pendingAckPromsRef.current.delete(ackProm));
}
```

**Cleanup** — drain in-flight ACKs before disconnecting:
```ts
return () => {
  cancelled = true;
  const subToClose = subRef.current;
  const cfToClose  = cfRef.current;
  subRef.current = null;
  cfRef.current  = null;

  const pending = [...pendingAckPromsRef.current];
  pendingAckPromsRef.current.clear();
  confirmedAckKeysRef.current.clear();

  Promise.allSettled(pending).then(() => {
    subToClose?.unsubscribe();
    cfToClose?.disconnect();
  });
};
```

`Promise.allSettled` ensures rejections do not block the drain.  Local
references (`subToClose`, `cfToClose`) are captured before nulling the shared
refs so that a subsequent effect run (StrictMode or sseInfo change) cannot
overwrite them mid-drain.

## Why This Is Safe

- The WebSocket stays open only for the duration of the pending ACK round-trip
  (~few ms to Centrifugo → backend → Redis).  No hardcoded time lag.
- After `cancelled = true`, new publications arriving during the brief drain
  window have `!cancelled === false`, so their ACK promises are not added to
  `pendingAckPromsRef` — they are fire-and-forget and will be handled by the
  backend's retry mechanism on a fresh connection.
- StrictMode double-invoke: the first cleanup sets `cancelled = true`, clears
  `pendingAckPromsRef`, and drains (nothing to drain since microtask deferred
  connection was also cancelled).  The second effect run starts fresh.
