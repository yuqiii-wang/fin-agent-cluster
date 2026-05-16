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
  /** Shared label for top-level nodes that form a conditional branch group.
   *  Enriched on the frontend from the graph topology; not returned by the
   *  nodes API.  Nodes with the same conditional_group are stacked vertically
   *  in a single topology slot with conditional (dashed) edge styling. */
  conditional_group?: string;
  /** True for topology placeholder nodes that have not yet executed. */
  is_topology_only?: boolean;
  /** Fork generation (0 = original run, 1+ = re-explore branches). */
  version: number;
  /** True if this node is the fork-point entry of a new branch. */
  is_forked: boolean;
  /** Version this branch was forked from (null for version 0). */
  forked_from_version?: number | null;
  /** IDs of predecessor nodes (from source version for forked nodes). */
  prev_node_ids: string[];
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  started_at?: string;
  elapsed_ms: number;
  updated_at?: string;
}
