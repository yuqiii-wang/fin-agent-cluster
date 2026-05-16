/** Graph topology types — mirrors backend/api/graph/topology.py */

export interface TopologyNodeDef {
  node_name: string;
  /** "Workflow" | "Subgraph" */
  node_type: string;
  /** When set, this node belongs to a conditional branch group. */
  conditional_group?: string;
  /** When set, this node belongs to a parallel fan-out/fan-in group at the top level. */
  parallel_group?: string;
}

export interface TopologyEdgeDef {
  from_node: string;
  to_node: string;
  kind: 'sequential' | 'conditional';
  /** Routing condition shown as an edge tooltip on hover. Only set on conditional edges. */
  condition_label?: string;
}

export interface GraphTopology {
  nodes: TopologyNodeDef[];
  edges: TopologyEdgeDef[];
}
