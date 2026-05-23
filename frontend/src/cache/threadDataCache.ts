/**
 * threadDataCache — session-level cache for terminal thread data.
 *
 * Keyed by `threadId`.  Only threads that have reached a terminal status
 * (completed / failed / cancelled) are stored — their nodes and tasks will
 * not change so caching is safe.
 *
 * Allows `useThreadData` to seed its state immediately from cache when the
 * user navigates back to a finished thread, avoiding redundant backend calls.
 */

import type { GraphTopology, NodeInfo, QueryResponse, TaskInfo } from '../types';

export interface ThreadCacheEntry {
  thread: QueryResponse;
  nodes: NodeInfo[];
  tasks: TaskInfo[];
  topology: GraphTopology | null;
}

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

/** Module-level topology singleton — same static topology for all threads. */
let _topology: GraphTopology | null = null;

export function getCachedTopology(): GraphTopology | null {
  return _topology;
}

export function setCachedTopology(t: GraphTopology): void {
  _topology = t;
}

const _cache = new Map<string, ThreadCacheEntry>();

/** Return cached thread data, or null if not yet cached or not terminal. */
export function getCachedThreadData(threadId: string): ThreadCacheEntry | null {
  return _cache.get(threadId) ?? null;
}

/**
 * Store thread data.  The entry is only written when the thread is in a
 * terminal status so live/polling threads are never frozen in stale state.
 */
export function setCachedThreadData(entry: ThreadCacheEntry): void {
  if (!TERMINAL_STATUSES.has(entry.thread.status)) return;
  _cache.set(entry.thread.thread_id, entry);
}

/** Remove a thread's cache entry (e.g. after a re-explore fork). */
export function evictThreadData(threadId: string): void {
  _cache.delete(threadId);
}
