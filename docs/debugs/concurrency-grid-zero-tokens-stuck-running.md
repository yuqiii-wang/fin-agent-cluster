# Debug: Concurrency Grid — 0 Tokens / Thread Stuck at "Running"

## Symptoms (5-thread concurrency test)

| Thread Status | Stream Task | Tokens | ACK % |
|---|---|---|---|
| Completed | Completed | 0 | 96% |
| Completed | Completed | 0 | 96% |
| Running   | Completed | 0 | 85% |
| Running   | Completed | 75/303 | 96% |

- Some threads completed successfully (tokens received, 100% acks).
- Other threads: LLM streaming produced 0 tokens despite thread completing.
- Some threads stuck at "Running" even though Stream Task shows "Completed".

---

## Root Cause 1 — Backend Race: `set_viewer` after `dispatch_graph_run`

**File:** `backend/users/queries.py` → `submit_query`

**Bad ordering:**
```python
await dispatch_graph_run(thread_id, request.query)   # ← graph starts
await set_thread_user(thread_id, str(user.id))
await set_viewer(str(user.id), thread_id)            # ← too late
```

**What happened:** Under high concurrency (5 simultaneous submits), the Celery
stream worker could pick up and execute `stream_task` before the `set_viewer`
write completed. In `stream_task._run_stream_async`:

```python
viewers_present = (
    await has_app_viewers(thread_id)    # Redis flag: fin:user:app_viewer:…
    and await has_thread_viewers(thread_id)  # Redis flag: fin:thread:viewer:…
)
```

If `has_thread_viewers` returned `False` (flag not yet written), `viewers_present = False`
and no tokens were published to the Redis Stream → 0 tokens at the frontend.

**Fix:** Move both `set_thread_user` and `set_viewer` **before** `dispatch_graph_run`:
```python
await set_thread_user(thread_id, str(user.id))
await set_viewer(str(user.id), thread_id)          # ← flags set before graph starts
await dispatch_graph_run(thread_id, request.query)
```

---

## Root Cause 2 — Frontend Drain Blocks Forever on Missing `ack_confirmed`

**File:** `frontend/src/components/ConcurrencyTest/useConcurrencyThread.ts`

The drain mechanism prevents setting thread status to "Completed" until all
sent ACK RPCs have received an `ack_confirmed` event. This guards against the
SSE connection being torn down before in-flight confirmations arrive.

**Bad behavior:** If a single `cf.rpc('thread_ack', ...)` call fails (e.g., the
Centrifugo connection closes while an RPC is in-flight, or the `ack_confirmed`
event is never delivered), `sentAckKeys.size > confirmedKeys.size` forever →
thread stays "Running" indefinitely.

**Observed:** 24 acks sent, 23 confirmed (96%) → drain never flushed.

**Fixes applied:**
1. **Drain timeout:** After `wantsClose = true` (done event received), start a
   5-second timer. If the drain hasn't flushed by then, force-complete anyway.
2. **RPC failure cleanup:** On `cf.rpc` failure (non-code-11 errors), remove the
   key from `sentAckKeysRef` and decrement `acksSentRef`. This keeps the
   sent/confirmed ratio accurate and allows `checkDrain` to succeed normally.

---

## Root Cause 3 — ACK % Never 100% → Confirmed < Sent

Under concurrency, some `ack_confirmed` events could arrive on the SSE channel
before the Centrifugo subscription was fully established. With Centrifugo history
recovery (`force_recovery: true`), these are replayed on connect. However if
the `cf.rpc` itself fails (e.g., RPC timeout, network glitch), the backend never
receives the ACK and never publishes `ack_confirmed`.

The fix for Root Cause 2 handles this: RPC failure removes the key from
`sentAckKeys`, restoring accuracy.

---

## How to Reproduce (before fix)

1. Submit 5 concurrent queries (Concurrency Test mode, 5 threads).
2. Observe the grid: some rows show 0 tokens, some stuck "Running".
3. Check backend logs: `[stream_task]` entries with `viewers=False`.

---

## Verification

Run the Playwright test:
```bash
cd frontend && npx playwright test tests/concurrency-test.spec.ts --headed
```

Expected: all 5 rows show Completed, tokens > 0, ACK = 100%.
