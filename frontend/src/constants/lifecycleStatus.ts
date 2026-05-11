/**
 * lifecycleStatus — canonical lifecycle status groupings for thread, node, and task.
 *
 * Single source of truth for which statuses represent an **active** (in-flight)
 * lifecycle and which represent a **terminal** (ended) lifecycle.
 *
 * Mirrors backend/db/postgres/lifecycle_status.py — keep both in sync.
 *
 * Thread-level (query_status):
 *   Active   : connecting | received | running
 *   Terminal : completed  | failed   | cancelled
 *
 * Node/task-level (work_status):
 *   Active   : pending | running
 *   Terminal : completed | failed | cancelled | wrong
 */

// ---------------------------------------------------------------------------
// Thread-level (query_status)
// ---------------------------------------------------------------------------

/** Statuses meaning the thread has started and is still in progress. */
export const ACTIVE_QUERY_STATUSES = new Set([
  'connecting',
  'received',
  'running',
] as const);

/** Statuses meaning the thread has reached an end state. */
export const TERMINAL_QUERY_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
] as const);

// ---------------------------------------------------------------------------
// Node / task level (work_status)
// ---------------------------------------------------------------------------

/** Statuses meaning the node/task has started and is still in progress. */
export const ACTIVE_WORK_STATUSES = new Set([
  'pending',
  'running',
] as const);

/** Statuses meaning the node/task has reached an end state. */
export const TERMINAL_WORK_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'wrong',
] as const);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns true if the thread status is terminal (lifecycle ended). */
export function isThreadTerminal(status: string): boolean {
  return TERMINAL_QUERY_STATUSES.has(status as never);
}

/** Returns true if the thread status is active (lifecycle in progress). */
export function isThreadActive(status: string): boolean {
  return ACTIVE_QUERY_STATUSES.has(status as never);
}

/** Returns true if the node/task status is terminal. */
export function isWorkTerminal(status: string): boolean {
  return TERMINAL_WORK_STATUSES.has(status as never);
}

/** Returns true if the node/task status is active. */
export function isWorkActive(status: string): boolean {
  return ACTIVE_WORK_STATUSES.has(status as never);
}
