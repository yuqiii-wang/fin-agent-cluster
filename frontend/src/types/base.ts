/**
 * Generic base envelope interfaces mirroring backend langgraph/models/base.py.
 *
 * These carry identity fields (thread_id, node_id, task_id, …) plus a typed
 * `content` payload — the same two-layer structure used on the backend.
 */

/** Base envelope for task inputs. */
export interface BaseTaskInput<T> {
  thread_id: string;
  node_id: string;
  task_id: string;
  task_name: string;
  metadata: Record<string, unknown>;
  content: T;
}

/** Base envelope for task outputs. */
export interface BaseTaskOutput<T> {
  thread_id: string;
  node_id: string;
  task_id: string;
  task_name: string;
  metadata: Record<string, unknown>;
  content: T;
}

/** Base envelope for node inputs. */
export interface BaseNodeInput<T> {
  thread_id: string;
  node_id: string;
  node_name: string;
  metadata: Record<string, unknown>;
  content: T;
}

/** Base envelope for node outputs. */
export interface BaseNodeOutput<T> {
  thread_id: string;
  node_id: string;
  node_name: string;
  metadata: Record<string, unknown>;
  content: T;
}

/** Base SSE notification envelope for thread-level events. */
export interface BaseThreadSseNotification<T> {
  thread_id: string;
  event: string;
  status: string;
  metadata: Record<string, unknown>;
  content: T;
}

/** Base SSE notification envelope for node-level events. */
export interface BaseNodeSseNotification<T> {
  thread_id: string;
  node_id: string;
  node_name: string;
  event: string;
  status: string;
  metadata: Record<string, unknown>;
  content: T;
}

/** Base SSE notification envelope for task-level events. */
export interface BaseTaskSseNotification<T> {
  thread_id: string;
  task_id: string;
  node_id: string;
  node_name: string;
  task_name: string;
  event: string;
  status: string;
  metadata: Record<string, unknown>;
  content: T;
}
