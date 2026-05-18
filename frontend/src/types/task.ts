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
  /** Task-level view type: Streaming | WebRequest | Stats | ToolCall | Markdown | Json. */
  view_type?: string;
  /** Ordered list of stats_view_types applicable to this task (Stats view only). */
  stats_views?: string[];
  /** True when this task streams LLM tokens in real-time (set by backend). */
  is_streaming?: boolean;
  /** Per-field view schema for hybrid tasks (e.g. {"thinking": "Markdown", "answer": "Json"}). */
  view_schema?: Record<string, string>;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}
