/**
 * Types for the graph visualization panel.
 *
 * Graph topology is derived from SSE events:
 *   graph_topology_init → pre-populates outer nodes (incl. subgraph containers) + stores topology
 *   node_input  → creates a GraphNode, records parent_node_execution_id for edges
 *   node_output → marks a node completed, sets elapsed_ms
 *   node_status → updates node status
 *   started     → creates a GraphTask
 *   completed/failed/cancelled → updates a GraphTask
 *   done        → marks the session as finished
 */

// ── Topology descriptors (from graph_topology_init SSE event) ────────────────

export interface GraphTopologyNode {
  node_name: string;
  parent_node_names: string[];
  node_type: "Typical" | "Subgraph" | "Reference";
}

export interface InnerSubgraphTopology {
  nodes: GraphTopologyNode[];
}

export interface GraphTopology {
  /** Outer-level nodes including subgraph containers and outer typical nodes. */
  outer_nodes: GraphTopologyNode[];
  /** Inner topology keyed by subgraph container node name. */
  subgraphs: Record<string, InnerSubgraphTopology>;
}

// ── Execution graph types ────────────────────────────────────────────────────

export interface GraphNode {
  /** DB PK of the node_executions row — used for edge topology. */
  node_execution_id: number;
  /** Governance UUID from node_status SSE event (may arrive after node_input). */
  node_id?: string;
  /** FK to parent node_executions — empty array for root nodes, multiple for fan-in nodes. */
  parent_node_execution_ids: number[];
  /** Human-readable node name. */
  node_name: string;
  /** Current lifecycle status. */
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "paused";
  /** Wall-clock ms when the node_input SSE event arrived. */
  started_at_ms: number;
  /** Wall-clock ms when the node reached a terminal status. */
  ended_at_ms?: number;
  /** Derived elapsed time in ms. */
  elapsed_ms?: number;
  /** Input snapshot from the node_input SSE event. */
  input?: Record<string, unknown>;
  /** Output snapshot from the node_output SSE event. */
  output?: Record<string, unknown>;
  /** Node type from backend registry: "Typical", "Subgraph", or "Reference". */
  node_type?: string;
  /**
   * For inner nodes: the name of their parent subgraph container.
   * Undefined for outer-graph nodes.
   */
  subgraph_parent?: string;
  /**
   * True for synthetic subgraph container nodes pre-created from topology.
   * These nodes have no real node_execution_id from the DB.
   */
  is_synthetic?: boolean;
}

export interface GraphTask {
  task_id: string;
  node_name: string;
  task_name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  started_at_ms: number;
  ended_at_ms?: number;
  elapsed_ms?: number;
  /** Input snapshot from the started SSE event extra_payload. */
  input?: Record<string, unknown>;
  output: Record<string, unknown>;
}

export interface GraphState {
  nodes: GraphNode[];
  tasks: GraphTask[];
  isDone: boolean;
  doneStatus?: string;
  /** Static topology received from graph_topology_init event. */
  topology?: GraphTopology;
}

export const EMPTY_GRAPH_STATE: GraphState = {
  nodes: [],
  tasks: [],
  isDone: false,
};

/**
 * Discriminated union of all events that mutate graph state.
 */
export type GraphEvent =
  | { type: "node_input"; node_execution_id: number; node_name: string; parent_node_execution_ids: number[]; input: Record<string, unknown>; node_type?: string; subgraph_parent?: string; ts: number }
  | { type: "node_output"; node_execution_id: number; node_name: string; output: Record<string, unknown>; elapsed_ms: number; ended_at_ms?: number; ts: number }
  | { type: "node_status"; node_id: string; node_name: string; status: string; ended_at_ms?: number; ts: number }
  | { type: "task_started"; task_id: string; node_name: string; task_name: string; input: Record<string, unknown>; ts: number }
  | { type: "task_terminal"; task_id: string; node_name: string; task_name: string; status: string; output: unknown; ts: number }
  | { type: "done"; status: string; ts: number }
  | { type: "reset" }
  | { type: "graph_topology_init"; outer_nodes: GraphTopologyNode[]; subgraphs: Record<string, InnerSubgraphTopology> };
