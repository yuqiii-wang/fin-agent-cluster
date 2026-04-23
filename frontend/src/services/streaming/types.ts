/**
 * Shared types for the streaming service layer.
 * Covers both regular fin streaming sessions and perf-test sessions.
 */

// ── Regular fin streaming ────────────────────────────────────────────────────

/** Connection / lifecycle state for a single fin stream session. */
export type FinStreamStatus =
  | "idle"          // no threadId provided
  | "connecting"    // SSE connection being established
  | "streaming"     // at least one `started` event received
  | "done"          // terminal `done` event received; SSE closed cleanly
  | "disconnected"; // unexpectedly closed or task already done before connect

/** A live snapshot of a single agent task accumulated from SSE events. */
export interface FinTaskSnapshot {
  task_id: number;
  node_name: string;
  task_key: string;
  status: "running" | "completed" | "failed" | "cancelled";
  output: Record<string, unknown>;
}
