# UI Rendering Performance Guide — Concurrent Streams

## Problem

With hundreds of parallel SSE streams, button clicks (Add / Cancel All / Restart)
become sluggish or unresponsive.

**Root cause:** `onPerfTokenBatch` called `setSessions(prev => prev.map(...))` on
every SSE token event.

```
100 streams × 50 token events/s = 5,000 setSessions calls/s
→ 5,000 full React re-renders/s of the 100-row Table
→ JS main thread saturated → button clicks queue behind renders
```

---

## Fix Architecture

### Token batching (ref-buffer → tick-flush)

```
SSE event (onPerfTokenBatch)
  ↓
pendingTokenPatchesRef.current.set(thread_id, accumulated_patch)   ← no React update
  ↓
100ms setInterval tick
  ↓
setSessions(prev => prev.map(apply all buffered patches))           ← ONE React update
```

**Result:** Re-render rate capped at ≤ 10/s regardless of stream count.

### AggregateStatsHeader decoupled from sessions array

Before:
```tsx
// Re-computed on every 100ms token flush, O(n × history_length) each time
<AggregateStatsHeader sessions={sessions} />
```

After:
```tsx
// Updated once/second on the 1s sub-tick inside useSessionManager
<AggregateStatsHeader stats={aggregateStats} />
```

### `setTick` removed

The old tick used `setTick((t) => t + 1)` as a dummy state update to force 100ms
re-renders.  The patch-flush `setSessions` now serves this purpose — one fewer
re-render cycle per tick when no patches exist.

---

## Files Changed

| File | What changed |
|---|---|
| `types.ts` | Added `PendingTokenPatch` interface |
| `usePerfSession.ts` | `onPerfTokenBatch` writes to `pendingTokenPatchesRef` instead of `setSessions` |
| `useSessionManager.ts` | 100ms tick flushes patches; `setTick` removed; `aggregateStats` computed on 1s sub-tick; `freezeAll`/`handleRestart` clear the patch buffer |
| `AggregateStatsHeader.tsx` | Prop changed from `sessions` → `stats: AggregateStats` |

---

## Diagnostic Logs

| Log prefix | When | What it shows |
|---|---|---|
| `[perf-render] tick-flush` | Every ~5 s | `patches=N total_delta=N sessions=N` — flush volume |
| `[perf-render] handleAddRequest` | On button click | `count`, `pending_patches`, `sessions` — measures click-to-submit latency |
| `[perf-render] cancel-all` | On button click | `active`, `pending_patches` |

Use browser DevTools **Performance** tab → record 5 s with 100 streams → confirm
`setSessions` flame-chart spikes are gone and the main thread is free for clicks.

---

## PendingTokenPatch Fields

```ts
interface PendingTokenPatch {
  tokensDelta: number;        // accumulated tokens since last tick
  last_token_ms: number;      // timestamp of most recent batch
  first_token_ms: number;     // timestamp of very first batch → digest_start_ms
  batch_first / max / ave / last: number;
  stream_text: string;        // latest rolling token text
  status_transition?: "digesting";     // promote pre-digest status once
  forceTokensTotal?: number;  // override s.tokens on the final batch
}
```

`forceTokensTotal` is set on the last batch so the displayed token count freezes
at the exact closure-tracked total rather than a stale React-state value.

---

## Key Invariants

- `onPerfTokenBatch` **never** calls `setSessions` — only writes to the ref.
- The terminal path (`isLastBatch`) calls `flushPendingForSession(thread_id)` 
  **synchronously before** `closeSession` to guarantee the final count reaches
  React state before `closed: true` is set.
- `freezeAll` and `handleRestart` call `pendingTokenPatchesRef.current.clear()`
  so stale patches from closed sessions are never applied after a reset.
