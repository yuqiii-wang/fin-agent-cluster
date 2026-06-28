/** Graph topology types — mirrors backend/api/graph/topology.py */

export interface TopologyNodeDef {
  node_name: string;
  /** "Workflow" | "Subgraph" */
  node_type: string;
  /** When set, this node belongs to a conditional branch group. */
  conditional_group?: string;
  /** When set, this node belongs to a parallel fan-out/fan-in group at the top level. */
  parallel_group?: string;
  /** When set, this node should be drawn on the same y-coordinate / "horizon" as
   *  the referenced node.  Used for multi-step branches such as
   *  ``prepare_peers -> load_peers_stats``: the second node sits in a later
   *  topology slot but must share its predecessor's row. */
  align_with_node_name?: string;
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

/** Mirrors backend/api/graph/node_metas.py — NodeConfigField */
export interface NodeConfigField {
  key: string;
  label: string;
  type: 'boolean' | 'select' | 'number';
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  description: string;
}

/** Mirrors backend/api/graph/node_metas.py — NodeMetaResponse */
export interface NodeMeta {
  node_name: string;
  display_name: string;
  category: string;
  fields: NodeConfigField[];
}
