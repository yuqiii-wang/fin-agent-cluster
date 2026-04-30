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

---

## Virtual Table (antd `virtual` prop)

### Problem

With 50–500 rows the antd `<Table>` renders every row's DOM nodes at once.
Each 100ms token flush triggers a full reconcile of all row subtrees even when
only a handful changed.  On slow hardware this shows as jank during scrolling.

### Solution

antd Table ships with a `virtual` prop (backed by `rc-virtual-list`) that only
mounts DOM nodes for rows currently visible in the scroll window — typically
10–30 rows — regardless of how many sessions exist in `dataSource`.

```tsx
<Table
  virtual
  scroll={{ y: tableScrollY }}   // ← must be a NUMBER, not a CSS string
  ...
/>
```

### `scroll.y` must be a number

`rc-virtual-list` does its own scroll-position arithmetic and expects a numeric
`height` in pixels.  Passing a CSS string like `"calc(100vh - 200px)"` is parsed
as `NaN`, which collapses the virtual container to zero height.  The collapsed
container renders on top of the content as an invisible overlay and **intercepts
all pointer events** — clicks, selections, and identity-cell toggles stop working.

The fix is to compute the height as a number in JavaScript:

```tsx
// Track window height reactively
const [windowHeight, setWindowHeight] = useState(() => window.innerHeight);
useEffect(() => {
  const handler = () => setWindowHeight(window.innerHeight);
  window.addEventListener("resize", handler);
  return () => window.removeEventListener("resize", handler);
}, []);

// Measure the sticky header height with a ResizeObserver
const [stickyHeaderH, setStickyHeaderH] = useState(0);

// tableSection padding = top 12px + bottom 16px = 28px
const tableScrollY = Math.max(200, windowHeight - stickyHeaderH - 28);

// Pass as a number — rc-virtual-list understands pixels, not CSS expressions
<Table virtual scroll={{ y: tableScrollY }} ... />
```

### Interaction with row expansion (accordion cells)

When an `IdentityStack` cell is toggled its row height changes.  With virtualization
every expanded row must be controlled from the parent so the virtual list can
measure row height consistently:

```tsx
// ❌ local state — virtual list cannot observe height changes driven from outside
function IdentityStack({ record }) {
  const [expanded, setExpanded] = useState(false);
  ...
}

// ✅ controlled — parent drives state; height change is a React render, measurable
function IdentityStack({ record, expanded, onToggle }) { ... }
```

The parent holds `expandedIdentityId: string | null` (accordion: only one row
open at a time) and passes `expanded={expandedIdentityId === record.thread_id}`
to each cell, ensuring `rc-virtual-list` re-renders the affected row when its
height changes.

### Summary

| Requirement | Reason |
|---|---|
| `scroll.y` must be a JS number | `rc-virtual-list` arithmetic — CSS strings parse as `NaN` |
| `scroll.y` tracked via `resize` listener | Container height changes with window resize |
| Sticky header height measured with `ResizeObserver` | Header height changes with config form visibility |
| Expanded cells must be controlled from parent | Virtual list must observe all row height changes |
