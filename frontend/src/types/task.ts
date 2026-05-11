/** Task execution info aligned to backend TaskInfo schema. */

/** Execution record for an individual task within a node. */
export interface TaskInfo {
  task_id: string;
  thread_id: string;
  node_id?: string;
  node_name: string;
  task_name: string;
  /** WorkStatus string value. */
  status: string;
  /** True when this task streams LLM tokens in real-time (set by backend). */
  is_streaming?: boolean;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}
