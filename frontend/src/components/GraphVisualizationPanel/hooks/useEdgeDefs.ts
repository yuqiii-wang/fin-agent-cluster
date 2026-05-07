import { useMemo } from "react";
import type { GraphNode, GraphTopology } from "../types";
import type { NodeLayout, InnerNodePosition } from "../layout";

export interface EdgeDef {
  key: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
}

export function useOuterEdgeDefs(
  hasTopology: boolean,
  topology: GraphTopology | null | undefined,
  layouts: NodeLayout[],
  visibleNodes: GraphNode[],
): EdgeDef[] {
  const layoutByName = useMemo(
    () => new Map(layouts.map((l) => [l.node.node_name, l])),
    [layouts],
  );
  return useMemo((): EdgeDef[] => {
    if (hasTopology && topology) {
      return topology.outer_nodes.flatMap((tn) =>
        tn.parent_node_names.flatMap((parentName) => {
          const from = layoutByName.get(parentName);
          const to = layoutByName.get(tn.node_name);
          if (!from || !to) return [];
          return [{ key: `${parentName}-${tn.node_name}`, fromX: from.cx + from.r, fromY: from.cy, toX: to.cx - to.r, toY: to.cy }];
        })
      );
    }
    const idToLayout = new Map(layouts.map((l) => [l.node.node_execution_id, l]));
    return visibleNodes.flatMap((node) =>
      node.parent_node_execution_ids.flatMap((parentId) => {
        const from = idToLayout.get(parentId);
        const to = idToLayout.get(node.node_execution_id);
        if (!from || !to) return [];
        return [{ key: `${parentId}-${node.node_execution_id}`, fromX: from.cx + from.r, fromY: from.cy, toX: to.cx - to.r, toY: to.cy }];
      })
    );
  }, [hasTopology, topology, layoutByName, visibleNodes]);
}

export function useInnerEdgeDefs(
  topoNodes: Array<{ node_name: string; parent_node_names: string[] }> | null,
  innerPositions: InnerNodePosition[],
): EdgeDef[] {
  return useMemo((): EdgeDef[] => {
    if (!topoNodes || innerPositions.length === 0) return [];
    const posMap = new Map(innerPositions.map((p) => [p.node_name, p]));
    return topoNodes.flatMap((tn) =>
      tn.parent_node_names.flatMap((parentName) => {
        const from = posMap.get(parentName);
        const to = posMap.get(tn.node_name);
        if (!from || !to) return [];
        return [{ key: `inner-${parentName}-${tn.node_name}`, fromX: from.cx + from.r, fromY: from.cy, toX: to.cx - to.r, toY: to.cy }];
      })
    );
  }, [topoNodes, innerPositions]);
}
