import { useMemo } from "react";
import type { GraphNode, GraphTopology, GraphTopologyNode } from "../types";
import { computeInnerLayout } from "../layout";
import type { InnerNodePosition } from "../layout";

export interface InnerGraphData {
  topoNodes: GraphTopologyNode[];
  displayNodes: GraphNode[];
}

export interface InnerGraphResult {
  expandedInnerData: InnerGraphData | null;
  innerPositions: InnerNodePosition[];
  innerNodeLayouts: Array<{ node: GraphNode; cx: number; cy: number; r: number }>;
  innerSvgW: number;
  innerSvgH: number;
}

export function useInnerGraph(
  expandedSubgraph: string | null,
  topology: GraphTopology | null | undefined,
  nodes: GraphNode[],
): InnerGraphResult {
  const expandedInnerData = useMemo((): InnerGraphData | null => {
    if (!expandedSubgraph || !topology) return null;
    const topoNodes = topology.subgraphs[expandedSubgraph]?.nodes ?? [];
    const displayNodes: GraphNode[] = topoNodes.map((tn, i) => {
      const live = nodes.find((n) => n.subgraph_parent === expandedSubgraph && n.node_name === tn.node_name);
      if (live) return live;
      return {
        node_execution_id: -9000 - i,
        parent_node_execution_ids: [],
        node_name: tn.node_name,
        status: "pending" as const,
        started_at_ms: 0,
        node_type: tn.node_type,
        subgraph_parent: expandedSubgraph,
        is_synthetic: true,
      };
    });
    return { topoNodes, displayNodes };
  }, [expandedSubgraph, topology, nodes]);

  const { positions: innerPositions, svgW: innerSvgW, svgH: innerSvgH } = useMemo(() => {
    if (!expandedInnerData) return { positions: [], svgW: 0, svgH: 0 };
    return computeInnerLayout(expandedInnerData.topoNodes);
  }, [expandedInnerData]);

  const innerNodeLayouts = useMemo(() => {
    if (!expandedInnerData) return [];
    return innerPositions
      .map((pos) => {
        const node = expandedInnerData.displayNodes.find((n) => n.node_name === pos.node_name);
        if (!node) return null;
        return { node, cx: pos.cx, cy: pos.cy, r: pos.r };
      })
      .filter(Boolean) as Array<{ node: GraphNode; cx: number; cy: number; r: number }>;
  }, [innerPositions, expandedInnerData]);

  return { expandedInnerData, innerPositions, innerNodeLayouts, innerSvgW, innerSvgH };
}
