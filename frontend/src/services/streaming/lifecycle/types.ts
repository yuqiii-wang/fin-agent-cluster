/**
 * Lifecycle types for the streaming done-handshake protocol.
 *
 * The backend emits a `done` signal when the query session is complete.
 * The frontend must:
 *   1. Enter the `"draining"` phase (verify all expected events have arrived).
 *   2. Satisfy every registered DoneConditionFn (or let the drain window expire).
 *   3. Send a done-ACK to the backend.
 *   4. Transition to the terminal `"done"` phase.
 *
 * This is handled by DoneConditionGuard in ./doneGuard.ts.
 */

// ── Lifecycle phases ─────────────────────────────────────────────────────────

/**
 * Full lifecycle phase for a streaming session, shared by both
 * useFinStreamSession and usePerfSession.
 *
 * State machine:
 *
 *   idle ──────────────────────────────────────────────────────► (stays idle if no threadId)
 *
 *   idle ──► connecting ──► streaming ──► draining ──► done
 *                                │                      ▲
 *                                └──► disconnected ─────╯ (unexpected close)
 *
 * `draining`: backend `done` signal received; DoneConditionGuard is checking
 *   that all expected events (tasks terminal, tokens drained) have arrived
 *   before sending the done-ACK and marking the session complete.
 */
export type StreamLifecyclePhase =
  | "idle"          // no threadId provided
  | "connecting"    // SSE connection being established
  | "streaming"     // at least one `started` event received
  | "draining"      // done signal received; awaiting drain conditions + ACK
  | "done"          // ACK sent; UI marked complete; SSE closed
  | "disconnected"; // unexpectedly closed or task already done before connect

// ── DoneConditionGuard options ────────────────────────────────────────────────

/**
 * A predicate that must return `true` before the done-ACK is sent.
 * Called synchronously on every recheck() call.
 */
export type DoneConditionFn = () => boolean;

export interface DoneGuardOptions {
  /**
   * Human-readable label used in log messages (e.g. "fin:threadId",
   * "perf:threadId").
   */
  label: string;

  /**
   * Conditions that must ALL return `true` before `onReady` is called.
   * If empty, the guard resolves immediately on `trigger()`.
   */
  conditions: DoneConditionFn[];

  /**
   * Callback invoked exactly once when all conditions are satisfied or
   * the drain window expires.
   *
   * @param forced - `true` when the drain window expired before all
   *   conditions were met; `false` when conditions were satisfied normally.
   */
  onReady: (forced: boolean) => void;

  /**
   * Maximum time to wait for all conditions to be satisfied (ms).
   * After this window, `onReady(true)` is called regardless.
   * Default: 3000 ms.
   */
  drainWindowMs?: number;
}
