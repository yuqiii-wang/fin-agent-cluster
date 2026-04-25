/**
 * Shared types for the streaming service layer.
 * Covers both regular fin streaming sessions and perf-test sessions.
 */

// ── Regular fin streaming ────────────────────────────────────────────────────

/**
 * Connection / lifecycle state for a single fin stream session.
 *
 * State machine:
 *
 *   idle ──► connecting ──► streaming ──► draining ──► done
 *                                │
 *                                └──► disconnected
 *
 * `draining`: backend `done` signal received; DoneConditionGuard is verifying
 *   that all expected task-terminal events have arrived before sending the
 *   done-ACK and marking the session complete.
 */
export type FinStreamStatus =
  | "idle"          // no threadId provided
  | "connecting"    // SSE connection being established
  | "streaming"     // at least one `started` event received
  | "draining"      // done signal received; awaiting drain conditions + ACK
  | "done"          // ACK sent; UI marked complete; SSE closed cleanly
  | "disconnected"; // unexpectedly closed or task already done before connect

/** A live snapshot of a single agent task accumulated from SSE events. */
export interface FinTaskSnapshot {
  task_id: number;
  node_name: string;
  task_key: string;
  status: "running" | "completed" | "failed" | "cancelled";
  output: Record<string, unknown>;
}
