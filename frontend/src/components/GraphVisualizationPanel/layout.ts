import type { GraphNode } from "./types";

// ── Layout constants ──────────────────────────────────────────────────────────
export const NODE_R = 36;           // circle radius for typical nodes
export const SUBGRAPH_R = 52;       // circle radius for subgraph container nodes
export const COL_W = 150;           // horizontal spacing between column centers (wider for subgraph nodes)
export const ROW_H = 120;           // vertical spacing between node centers in same col
export const PAD_X = 70;            // left/right padding
export const PAD_Y = 70;            // top/bottom padding
export const LABEL_OFFSET = 14;     // text below circle bottom edge

/** Return the circle radius for a node based on its type. */
export function getNodeRadius(node: GraphNode): number {
  return node.node_type === "Subgraph" ? SUBGRAPH_R : NODE_R;
}

// ── Status colors ─────────────────────────────────────────────────────────────
export const STATUS_COLORS: Record<string, string> = {
  pending:   "#8c8c8c",
  running:   "#1677ff",
  completed: "#52c41a",
  failed:    "#ff4d4f",
  cancelled: "#fa8c16",
  paused:    "#faad14",
};

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "#8c8c8c";
}

export function fmtElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Layout types ──────────────────────────────────────────────────────────────

export interface NodeLayout {
  node: GraphNode;
  cx: number;
  cy: number;
  /** Effective radius used for this node (accounts for subgraph nodes). */
  r: number;
}

// ── Layout computation ────────────────────────────────────────────────────────

export function computeLayout(
  nodes: GraphNode[],
  /** When provided (topology mode), depth is assigned by node_name instead of execution IDs. */
  topologyParentMap?: Map<string, string[]>,
): { layouts: NodeLayout[]; svgW: number; svgH: number } {
  if (nodes.length === 0) return { layouts: [], svgW: 0, svgH: 0 };

  const depthMap = new Map<number, number>(); // node_execution_id → depth

  if (topologyParentMap) {
    // Topology-based: use node_name → depth so synthetic container nodes get correct columns.
    const nameDepthMap = new Map<string, number>();
    const roots = nodes.filter((n) => (topologyParentMap.get(n.node_name) ?? []).length === 0);
    roots.forEach((n) => nameDepthMap.set(n.node_name, 0));
    let iter = 0;
    while (nameDepthMap.size < nodes.length && iter++ < 50) {
      for (const node of nodes) {
        if (nameDepthMap.has(node.node_name)) continue;
        const parents = topologyParentMap.get(node.node_name) ?? [];
        const parentDepths = parents
          .map((p) => nameDepthMap.get(p))
          .filter((d): d is number => d !== undefined);
        if (parentDepths.length > 0) nameDepthMap.set(node.node_name, Math.max(...parentDepths) + 1);
      }
    }
    nodes.forEach((n) => {
      if (!nameDepthMap.has(n.node_name)) nameDepthMap.set(n.node_name, 0);
      depthMap.set(n.node_execution_id, nameDepthMap.get(n.node_name)!);
    });
  } else {
    const idToNode = new Map<number, GraphNode>(nodes.map((n) => [n.node_execution_id, n]));
    const roots = nodes.filter((n) => n.parent_node_execution_ids.length === 0);
    roots.forEach((n) => depthMap.set(n.node_execution_id, 0));
    const queue = [...roots];
    while (queue.length > 0) {
      const curr = queue.shift()!;
      const currDepth = depthMap.get(curr.node_execution_id) ?? 0;
      nodes
        .filter((n) => n.parent_node_execution_ids.includes(curr.node_execution_id))
        .forEach((child) => {
          const prevDepth = depthMap.get(child.node_execution_id);
          const newDepth = currDepth + 1;
          if (prevDepth === undefined || newDepth > prevDepth) {
            depthMap.set(child.node_execution_id, newDepth);
          }
          if (idToNode.has(child.node_execution_id)) queue.push(child);
        });
    }
    nodes.forEach((n) => {
      if (!depthMap.has(n.node_execution_id)) depthMap.set(n.node_execution_id, 0);
    });
  }

  const byDepth = new Map<number, GraphNode[]>();
  nodes.forEach((n) => {
    const d = depthMap.get(n.node_execution_id) ?? 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(n);
  });

  const maxDepth = Math.max(...Array.from(depthMap.values()));
  const maxColSize = Math.max(...Array.from(byDepth.values()).map((g) => g.length));
  const maxR = Math.max(...nodes.map(getNodeRadius));

  const svgW = PAD_X * 2 + maxDepth * COL_W + maxR * 2;
  const svgH = PAD_Y * 2 + (maxColSize - 1) * ROW_H + maxR * 2 + LABEL_OFFSET + 14;

  const layouts: NodeLayout[] = [];
  byDepth.forEach((group, depth) => {
    const colCenterX = PAD_X + maxR + depth * COL_W;
    const totalH = (group.length - 1) * ROW_H;
    const startY = PAD_Y + maxR + (((maxColSize - 1) * ROW_H) - totalH) / 2;
    group.forEach((node, i) => {
      layouts.push({ node, cx: colCenterX, cy: startY + i * ROW_H, r: getNodeRadius(node) });
    });
  });

  return { layouts, svgW, svgH };
}

// ── Inner subgraph layout ─────────────────────────────────────────────────────

export const INNER_COL_W = 120;
export const INNER_ROW_H = 100;

export interface InnerNodePosition {
  node_name: string;
  cx: number;
  cy: number;
  r: number;
}

/**
 * Compute standalone layout for inner nodes of an expanded subgraph.
 * Returns positions in a self-contained coordinate system for a separate overlay SVG.
 */
export function computeInnerLayout(
  topologyNodes: Array<{ node_name: string; parent_node_names: string[] }>,
): { positions: InnerNodePosition[]; svgW: number; svgH: number } {
  if (topologyNodes.length === 0) return { positions: [], svgW: 0, svgH: 0 };

  const names = new Set(topologyNodes.map((n) => n.node_name));

  // BFS depth map using only intra-subgraph edges
  const depthMap = new Map<string, number>();
  for (const n of topologyNodes) {
    if (!n.parent_node_names.some((p) => names.has(p))) depthMap.set(n.node_name, 0);
  }
  let iter = 0;
  while (depthMap.size < topologyNodes.length && iter++ < 50) {
    for (const n of topologyNodes) {
      if (depthMap.has(n.node_name)) continue;
      const parentDepths = n.parent_node_names
        .filter((p) => names.has(p))
        .map((p) => depthMap.get(p))
        .filter((d): d is number => d !== undefined);
      if (parentDepths.length > 0) depthMap.set(n.node_name, Math.max(...parentDepths) + 1);
    }
  }
  for (const n of topologyNodes) {
    if (!depthMap.has(n.node_name)) depthMap.set(n.node_name, 0);
  }

  const maxDepth = Math.max(...Array.from(depthMap.values()));
  const byDepth = new Map<number, string[]>();
  depthMap.forEach((d, name) => {
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(name);
  });
  const maxColSize = Math.max(...Array.from(byDepth.values()).map((g) => g.length));

  const svgW = PAD_X * 2 + maxDepth * INNER_COL_W + NODE_R * 2;
  const svgH = PAD_Y * 2 + (maxColSize - 1) * INNER_ROW_H + NODE_R * 2 + LABEL_OFFSET + 14;

  const positions: InnerNodePosition[] = [];
  byDepth.forEach((group, depth) => {
    const cx = PAD_X + NODE_R + depth * INNER_COL_W;
    const totalH = (group.length - 1) * INNER_ROW_H;
    const startY = PAD_Y + NODE_R + (((maxColSize - 1) * INNER_ROW_H) - totalH) / 2;
    group.forEach((name, i) => {
      positions.push({ node_name: name, cx, cy: startY + i * INNER_ROW_H, r: NODE_R });
    });
  });

  return { positions, svgW, svgH };
}
