/** Node execution info aligned to backend NodeExecutionInfo schema. */

/** Execution record for a single graph node (GET /threads/{id}/nodes). */
export interface NodeInfo {
  node_id: string;
  thread_id: string;
  node_name: string;
  /** WorkStatus string value. */
  status: string;
  /** NodeType string value: "Typical" | "Reference" | "Subgraph". */
  type: string;
  parent_node_id?: string;
  /** Shared label for nodes that run concurrently inside the same subgraph.
   *  Nodes with the same parallel_group are shown stacked (fan-out/fan-in). */
  parallel_group?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  started_at?: string;
  elapsed_ms: number;
  updated_at?: string;
}
