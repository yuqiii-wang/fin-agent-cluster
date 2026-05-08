# Token Delivery Race: UI Stuck at "digesting"

## Symptom
Throughput-mode perf test sessions stay permanently in the **digesting** status.
`tokensReceived` never reaches `actualTokensExpected`, so the drain guard activates
and the session eventually closes with status `"timeout"` instead of `"completed"`.

## Root Cause

### Two-channel architecture
- **centrifugo-sse-{0,1}** — lifecycle events (`started`, `done`, `stream_complete`, …)
- **centrifugo-token-{0,1}** — token batches (`token_batch`)

Both subscriptions are opened in parallel from `openSessionStream`.
Each requires an async HTTP token-fetch before the WebSocket subscription is confirmed.

### The race window
1. `openSseStream` resolves quickly — SSE subscription is confirmed first.
2. The SSE stream receives `query_received` → the old code sent the ACK **immediately**.
3. Backend receives ACK → starts graph execution → dispatches Celery ingest task.
4. Celery ingest writes 100 k tokens to `fin:llm:tokens` in ~1 second (~107 XADD batches).
5. **Meanwhile**, the token stream `fetchCentrifugoToken` HTTP call + WS subscribe handshake
   for `centrifugo-token` might still be in flight (~50–200 ms).
6. Centrifugo processes early XADD entries and publishes them to `thread:{threadId}` channel
   **before** the browser subscription is confirmed.
7. `centrifugo-token` config has `force_recovery: true`, but `openTokenStream` used
   `recoverable: false` with no `since` position — the server has no position to recover
   from, so pre-subscription publications are **permanently lost**.
8. `tokensReceived = ~99 000 < actualTokensExpected = 100 000` → drain guard activated →
   session stuck at "digesting" for the full `timeoutSecs` window, then closes as "timeout".

## Fix

### `frontend/src/api/stream.ts`
Added `"onSubscribed"` to the `handlers` type of `openTokenStream` and wired it through
to the underlying `_createSubscription` call (was hardcoded `undefined`).

### `frontend/src/services/streaming/usePerfSession.ts`
Replaced `createAckHandlers` (which sent ACK immediately on `query_received`) with a
**gated ACK** pattern:

```
┌─────────────────────┐       ┌──────────────────────────┐
│  SSE subscription   │       │  Token subscription      │
│  confirmed first    │       │  confirmed (50–200 ms)   │
└─────────┬───────────┘       └────────────┬─────────────┘
          │ query_received                 │ onSubscribed
          ▼                               ▼
      ackQueryReceived = true         tokenStreamReady = true
          │                               │
          └──────────────┬────────────────┘
                         ▼
                    _tryAck() → only fires when BOTH conditions are true
                         │
                         ▼
                  POST /users/query/ack
                         │
                         ▼
                  Backend starts ingest
                  (token sub already confirmed → no race)
```

The ACK is held until **both**:
- `query_received` event arrives via the SSE channel, AND
- The token stream WebSocket subscription is confirmed (`onSubscribed` fires)

This guarantees the backend cannot write tokens before the browser is subscribed.

## Why not enable history recovery instead?

History recovery (`recoverable: true`, `since: { epoch: "", offset: 0 }`) would also
retrieve missed batches, but brings complications:
- Re-runs on the same `thread_id` within the 600 s history TTL would replay stale
  token batches from the previous run, inflating `tokensReceived`.
- Filtering by `stream_id` requires adding it to batch events and buffering batches
  until `onStarted` fires — more invasive.

The gated-ACK approach is simpler, correct, and adds no replay complexity.
