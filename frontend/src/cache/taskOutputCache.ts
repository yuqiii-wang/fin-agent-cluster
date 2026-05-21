/**
 * taskOutputCache — session-level cache for completed streaming task outputs.
 *
 * Keyed by `${threadId}:${taskId}`.  Only terminal (completed) task outputs
 * are stored — those records are immutable so caching is safe.
 *
 * Prevents repeated `GET /threads/{threadId}/tasks/{taskId}` calls when the
 * user navigates away from a task detail panel and returns to it.
 */

import type { TaskInfo } from '../types';

const _cache = new Map<string, TaskInfo>();

/** Return a cached full task record, or null if not yet cached. */
export function getCachedTaskOutput(threadId: string, taskId: string): TaskInfo | null {
  return _cache.get(`${threadId}:${taskId}`) ?? null;
}

/** Store a full task record.  Should only be called for completed tasks. */
export function setCachedTaskOutput(threadId: string, task: TaskInfo): void {
  _cache.set(`${threadId}:${task.task_id}`, task);
}

/** Remove a task output cache entry (e.g. after a retry or continue). */
export function evictCachedTaskOutput(threadId: string, taskId: string): void {
  _cache.delete(`${threadId}:${taskId}`);
}
