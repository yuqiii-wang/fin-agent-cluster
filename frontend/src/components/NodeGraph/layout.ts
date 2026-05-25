import type { NodeInfo } from '../../types';
import type { EdgeKind, InnerSlot, Layout, TopSlot } from './types';
import {
  MARGIN_X, SLOT_W_REGULAR, INNER_STEP, INNER_VERT_STEP, INNER_RADIUS,
  CENTER_Y, BUBBLE_PAD_X, BUBBLE_PAD_Y, COND_VERT_STEP, NODE_RADIUS,
  SVG_H,
} from './constants';

/** Group sibling nodes into ordered slots (parallel groups collapse into one slot). */
export function buildInnerSlots(children: NodeInfo[]): InnerSlot[] {
  const groupMap = new Map<string, NodeInfo[]>();
  for (const n of children) {
    if (n.parallel_group) {
      const arr = groupMap.get(n.parallel_group) ?? [];
      arr.push(n);
      groupMap.set(n.parallel_group, arr);
    }
  }

  const slots: InnerSlot[] = [];
  const seenGroups = new Set<string>();
  for (const n of children) {
    if (n.parallel_group) {
      if (!seenGroups.has(n.parallel_group)) {
        seenGroups.add(n.parallel_group);
        slots.push({ type: 'parallel', group: n.parallel_group, nodes: groupMap.get(n.parallel_group)! });
      }
    } else {
      slots.push({ type: 'single', node: n });
    }
  }
  return slots;
}

/** Group top-level nodes into ordered slots, collapsing conditional and parallel groups. */
export function buildTopSlots(topLevel: NodeInfo[]): TopSlot[] {
  const condGroupMap = new Map<string, NodeInfo[]>();
  const parGroupMap = new Map<string, NodeInfo[]>();
  for (const n of topLevel) {
    if (n.conditional_group) {
      const arr = condGroupMap.get(n.conditional_group) ?? [];
      arr.push(n);
      condGroupMap.set(n.conditional_group, arr);
    } else if (n.parallel_group) {
      const arr = parGroupMap.get(n.parallel_group) ?? [];
      arr.push(n);
      parGroupMap.set(n.parallel_group, arr);
    }
  }

  const slots: TopSlot[] = [];
  const seenGroups = new Set<string>();
  for (const n of topLevel) {
    if (n.conditional_group) {
      if (!seenGroups.has(n.conditional_group)) {
        seenGroups.add(n.conditional_group);
        slots.push({ type: 'conditional', group: n.conditional_group, nodes: condGroupMap.get(n.conditional_group)! });
      }
    } else if (n.parallel_group) {
      if (!seenGroups.has(n.parallel_group)) {
        seenGroups.add(n.parallel_group);
        slots.push({ type: 'parallel', group: n.parallel_group, nodes: parGroupMap.get(n.parallel_group)! });
      }
    } else {
      slots.push({ type: 'single', node: n });
    }
  }
  return slots;
}

/** Compute x/y positions, bubble bounds, and edge lists for all nodes. */
export function computeLayout(nodes: NodeInfo[], expandedSubgraphIds: Set<string> = new Set()): Layout {
  const topLevel = nodes.filter(n => !n.parent_node_id);
  const innerByParentId = new Map<string, NodeInfo[]>();
  for (const n of nodes) {
    if (n.parent_node_id) {
      const arr = innerByParentId.get(n.parent_node_id) ?? [];
      arr.push(n);
      innerByParentId.set(n.parent_node_id, arr);
    }
  }

  const topSlots = buildTopSlots(topLevel);

  // Compute slot widths: conditional/parallel slots use SLOT_W_REGULAR; subgraph slots may expand.
  const slotWidths = topSlots.map(slot => {
    if (slot.type === 'conditional') return SLOT_W_REGULAR;
    if (slot.type === 'parallel') return SLOT_W_REGULAR;
    const n = slot.node;
    const children = innerByParentId.get(n.node_id) ?? [];
    if (children.length === 0) return SLOT_W_REGULAR;
    if (!expandedSubgraphIds.has(n.node_id)) return SLOT_W_REGULAR;
    const innerSlots = buildInnerSlots(children);
    const innerSpan = Math.max(0, (innerSlots.length - 1) * INNER_STEP);
    return innerSpan + BUBBLE_PAD_X * 2 + INNER_RADIUS * 2 + 20;
  });

  const totalSlotW = slotWidths.reduce((a, b) => a + b, 0);
  const svgW = Math.max(480, totalSlotW + MARGIN_X * 2);

  const positions: Record<string, { x: number; y: number }> = {};
  const bubbles = new Map<string, import('./types').Bubble>();

  let curX = MARGIN_X;
  topSlots.forEach((slot, i) => {
    const slotW = slotWidths[i];
    const cx = curX + slotW / 2;

    if (slot.type === 'conditional') {
      // Stack conditional nodes vertically, centered at cx
      const count = slot.nodes.length;
      slot.nodes.forEach((n, k) => {
        const offsetY = (k - (count - 1) / 2) * COND_VERT_STEP;
        positions[n.node_name] = { x: cx, y: CENTER_Y + offsetY };
      });
    } else if (slot.type === 'parallel') {
      // Stack parallel nodes vertically, centered at cx (same spacing as conditional)
      const count = slot.nodes.length;
      slot.nodes.forEach((n, k) => {
        const offsetY = (k - (count - 1) / 2) * COND_VERT_STEP;
        positions[n.node_name] = { x: cx, y: CENTER_Y + offsetY };
      });
    } else {
      const n = slot.node;
      positions[n.node_name] = { x: cx, y: CENTER_Y };

      const children = innerByParentId.get(n.node_id) ?? [];
      if (children.length > 0) {
        const innerSlots = buildInnerSlots(children);
        const innerSpan = Math.max(0, (innerSlots.length - 1) * INNER_STEP);
        const startX = cx - innerSpan / 2;

        const maxParallel = Math.max(1, ...innerSlots.map(s => s.type === 'parallel' ? s.nodes.length : 1));
        const halfH = maxParallel > 1
          ? (maxParallel - 1) / 2 * INNER_VERT_STEP + INNER_RADIUS + BUBBLE_PAD_Y
          : INNER_RADIUS + BUBBLE_PAD_Y;

        innerSlots.forEach((innerSlot, j) => {
          const slotX = startX + j * INNER_STEP;
          if (innerSlot.type === 'single') {
            positions[innerSlot.node.node_name] = { x: slotX, y: CENTER_Y };
          } else {
            const cnt = innerSlot.nodes.length;
            innerSlot.nodes.forEach((cn, k) => {
              const offsetY = (k - (cnt - 1) / 2) * INNER_VERT_STEP;
              positions[cn.node_name] = { x: slotX, y: CENTER_Y + offsetY };
            });
          }
        });

        const bx = startX - INNER_RADIUS - BUBBLE_PAD_X;
        const bw = innerSpan + (INNER_RADIUS + BUBBLE_PAD_X) * 2;
        const by = CENTER_Y - halfH;
        const bh = halfH * 2;
        bubbles.set(n.node_id, { x: bx, y: by, w: bw, h: bh });
      }
    }

    curX += slotW;
  });

  // Build top-level edges from slot transitions, carrying EdgeKind
  const topEdges: Array<[string, string, EdgeKind]> = [];
  for (let i = 0; i < topSlots.length - 1; i++) {
    const curr = topSlots[i];
    const next = topSlots[i + 1];

    if (curr.type === 'single' && next.type === 'single') {
      topEdges.push([curr.node.node_name, next.node.node_name, 'sequential']);
    } else if (curr.type === 'single' && next.type === 'conditional') {
      // Always cond-fan-out; per-spur solid/dashed is resolved at render time
      for (const toNode of next.nodes) {
        topEdges.push([curr.node.node_name, toNode.node_name, 'cond-fan-out']);
      }
    } else if (curr.type === 'conditional' && next.type === 'single') {
      // Always cond-fan-in; per-spur solid/dashed is resolved at render time
      for (const fromNode of curr.nodes) {
        topEdges.push([fromNode.node_name, next.node.node_name, 'cond-fan-in']);
      }
    } else if (curr.type === 'single' && next.type === 'parallel') {
      for (const toNode of next.nodes) {
        topEdges.push([curr.node.node_name, toNode.node_name, 'fan-out']);
      }
    } else if (curr.type === 'parallel' && next.type === 'single') {
      for (const fromNode of curr.nodes) {
        topEdges.push([fromNode.node_name, next.node.node_name, 'fan-in']);
      }
    } else {
      // cross: conditional → conditional, parallel → parallel, etc.
      const fromNames = curr.type === 'single' ? [curr.node.node_name] : curr.nodes.map(n => n.node_name);
      const toNames   = next.type === 'single' ? [next.node.node_name] : next.nodes.map(n => n.node_name);
      for (const from of fromNames) {
        for (const to of toNames) {
          topEdges.push([from, to, 'cond-fan-out']);
        }
      }
    }
  }

  const innerEdges = new Map<string, Array<[string, string, EdgeKind]>>();
  for (const [parentId, children] of innerByParentId.entries()) {
    const innerSlots = buildInnerSlots(children);
    const edges: Array<[string, string, EdgeKind]> = [];
    for (let i = 0; i < innerSlots.length - 1; i++) {
      const curr = innerSlots[i];
      const next = innerSlots[i + 1];
      const fromNames = curr.type === 'single' ? [curr.node.node_name] : curr.nodes.map(cn => cn.node_name);
      const toNames   = next.type === 'single' ? [next.node.node_name] : next.nodes.map(cn => cn.node_name);
      const edgeKind: EdgeKind =
        fromNames.length === 1 && toNames.length === 1 ? 'sequential' :
        fromNames.length === 1 ? 'fan-out' : 'fan-in';
      for (const from of fromNames) {
        for (const to of toNames) {
          edges.push([from, to, edgeKind]);
        }
      }
    }
    innerEdges.set(parentId, edges);
  }

  // Compute dynamic height: ensure the SVG is tall enough to show all nodes
  // plus their labels (NODE_RADIUS + ~30px for label text and margin).
  const yValues = Object.values(positions).map(p => p.y);
  const maxNodeY = yValues.length > 0 ? Math.max(...yValues) : CENTER_Y;
  const svgH = Math.max(SVG_H, maxNodeY + NODE_RADIUS + 30);

  return { positions, svgW, svgH, topLevel, topSlots, innerByParentId, topEdges, innerEdges, bubbles };
}

/** Build an SVG line path between two circles, stopping at their radii. */
export function calcEdgePath(
  from: { x: number; y: number },
  to: { x: number; y: number },
  fromR: number,
  toR: number,
): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const x1 = from.x + (dx / dist) * fromR;
  const y1 = from.y + (dy / dist) * fromR;
  const x2 = to.x - (dx / dist) * toR;
  const y2 = to.y - (dy / dist) * toR;
  return `M ${x1} ${y1} L ${x2} ${y2}`;
}

/** Midpoint of the visible edge segment between two circles. */
export function calcEdgeMidpoint(
  from: { x: number; y: number },
  to: { x: number; y: number },
  fromR: number,
  toR: number,
): { x: number; y: number } {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const x1 = from.x + (dx / dist) * fromR;
  const y1 = from.y + (dy / dist) * fromR;
  const x2 = to.x - (dx / dist) * toR;
  const y2 = to.y - (dy / dist) * toR;
  return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
}
