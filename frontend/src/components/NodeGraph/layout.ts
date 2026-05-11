import type { NodeInfo } from '../../types';
import type { EdgeKind, InnerSlot, Layout } from './types';
import {
  MARGIN_X, SLOT_W_REGULAR, INNER_STEP, INNER_VERT_STEP, INNER_RADIUS,
  CENTER_Y, BUBBLE_PAD_X, BUBBLE_PAD_Y,
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

  const slotWidths = topLevel.map(n => {
    const children = innerByParentId.get(n.node_id) ?? [];
    if (children.length === 0) return SLOT_W_REGULAR;
    if (!expandedSubgraphIds.has(n.node_id)) return SLOT_W_REGULAR;
    const slots = buildInnerSlots(children);
    const innerSpan = Math.max(0, (slots.length - 1) * INNER_STEP);
    return innerSpan + BUBBLE_PAD_X * 2 + INNER_RADIUS * 2 + 20;
  });

  const totalSlotW = slotWidths.reduce((a, b) => a + b, 0);
  const svgW = Math.max(480, totalSlotW + MARGIN_X * 2);

  const positions: Record<string, { x: number; y: number }> = {};
  const bubbles = new Map<string, import('./types').Bubble>();

  let curX = MARGIN_X;
  topLevel.forEach((n, i) => {
    const slotW = slotWidths[i];
    const cx = curX + slotW / 2;
    positions[n.node_name] = { x: cx, y: CENTER_Y };

    const children = innerByParentId.get(n.node_id) ?? [];
    if (children.length > 0) {
      const slots = buildInnerSlots(children);
      const innerSpan = Math.max(0, (slots.length - 1) * INNER_STEP);
      const startX = cx - innerSpan / 2;

      const maxParallel = Math.max(1, ...slots.map(s => s.type === 'parallel' ? s.nodes.length : 1));
      const halfH = maxParallel > 1
        ? (maxParallel - 1) / 2 * INNER_VERT_STEP + INNER_RADIUS + BUBBLE_PAD_Y
        : INNER_RADIUS + BUBBLE_PAD_Y;

      slots.forEach((slot, j) => {
        const slotX = startX + j * INNER_STEP;
        if (slot.type === 'single') {
          positions[slot.node.node_name] = { x: slotX, y: CENTER_Y };
        } else {
          const count = slot.nodes.length;
          slot.nodes.forEach((cn, k) => {
            const offsetY = (k - (count - 1) / 2) * INNER_VERT_STEP;
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

    curX += slotW;
  });

  const topEdges: Array<[string, string]> = [];
  for (let i = 0; i < topLevel.length - 1; i++) {
    topEdges.push([topLevel[i].node_name, topLevel[i + 1].node_name]);
  }

  const innerEdges = new Map<string, Array<[string, string, EdgeKind]>>();
  for (const [parentId, children] of innerByParentId.entries()) {
    const slots = buildInnerSlots(children);
    const edges: Array<[string, string, EdgeKind]> = [];
    for (let i = 0; i < slots.length - 1; i++) {
      const curr = slots[i];
      const next = slots[i + 1];
      const fromNames = curr.type === 'single' ? [curr.node.node_name] : curr.nodes.map(cn => cn.node_name);
      const toNames   = next.type === 'single' ? [next.node.node_name] : next.nodes.map(cn => cn.node_name);
      const kind: EdgeKind =
        fromNames.length === 1 && toNames.length === 1 ? 'sequential' :
        fromNames.length === 1 ? 'fan-out' : 'fan-in';
      for (const from of fromNames) {
        for (const to of toNames) {
          edges.push([from, to, kind]);
        }
      }
    }
    innerEdges.set(parentId, edges);
  }

  return { positions, svgW, topLevel, innerByParentId, topEdges, innerEdges, bubbles };
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
