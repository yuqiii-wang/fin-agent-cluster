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
  // Defensive step: `align_with_node_name` means "render me as my own topology
  // slot on the same horizontal row as the referenced node".  Some backend nodes
  // also declare a non-empty `parallel_group` for database branch-identity
  // purposes, which would otherwise cause the UI to stack them as siblings.
  // Strip parallel_group whenever align_with_node_name is present so the
  // alignment hint always wins.
  const sanitizedNodes: NodeInfo[] = nodes.map(n => {
    if (!n.align_with_node_name) return n;
    const clone: NodeInfo = { ...n };
    delete (clone as { parallel_group?: string }).parallel_group;
    return clone;
  });

  const topLevel = sanitizedNodes.filter(n => !n.parent_node_id);
  const innerByParentId = new Map<string, NodeInfo[]>();
  for (const n of sanitizedNodes) {
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
      // If this node is a "continuation" of another node (e.g. load_peers_stats
      // continues prepare_peers), align it vertically with its predecessor so
      // the two-node branch shares the same horizon instead of jumping back to
      // CENTER_Y.  The predecessor was laid out in an earlier slot.
      let y = CENTER_Y;
      const alignRef = n.align_with_node_name;
      if (alignRef && positions[alignRef]) {
        y = positions[alignRef].y;
      }
      positions[n.node_name] = { x: cx, y };

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
            const innerN = innerSlot.node;
            let innerY = CENTER_Y;
            const innerAlign = innerN.align_with_node_name;
            if (innerAlign && positions[innerAlign]) {
              innerY = positions[innerAlign].y;
            }
            positions[innerN.node_name] = { x: slotX, y: innerY };
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
        const by = y - halfH;
        const bh = halfH * 2;
        bubbles.set(n.node_id, { x: bx, y: by, w: bw, h: bh });
      }
    }

    curX += slotW;
  });

  // Build top-level edges from slot transitions, carrying EdgeKind.
  //
  // Two-pass model:
  //   Pass 1 — emit edges between adjacent slots (slot-adjacency heuristic).
  //            Single→parallel produces `fan-out`; parallel→single produces
  //            `fan-in`; single→single produces `sequential`.
  //   Pass 2 — for every top-level slot whose members appear as predecessors
  //            of a *later* non-adjacent single-node slot (e.g. the 7 analysis
  //            nodes inside the parallel fan-out pointing to `final_report`
  //            even though `load_peers_stats` sits between them), emit extra
  //            `fan-in` edges.  This ensures multi-source merge nodes are drawn
  //            as a right-angle bus.
  //
  // `groupEdges` in NodeGraph.tsx then merges edges sharing the same source or
  // destination into a single `FanEdgeGroup`.  The runtime topology filter
  // (`isEdgeInTopology`) drops any spur that wasn't actually declared, so it is
  // safe to over-declare fan-in/fan-out candidates here.
  const topEdges: Array<[string, string, EdgeKind]> = [];

  // --- Pass 1: adjacent slot transitions ---
  function slotNodeNames(slot: TopSlot): string[] {
    if (slot.type === 'single') return [slot.node.node_name];
    return slot.nodes.map(n => n.node_name);
  }

  for (let i = 0; i < topSlots.length - 1; i++) {
    const curr = topSlots[i];
    const next = topSlots[i + 1];

    if (curr.type === 'single' && next.type === 'single') {
      topEdges.push([curr.node.node_name, next.node.node_name, 'sequential']);
    } else if (curr.type === 'single' && next.type === 'conditional') {
      for (const toNode of next.nodes) {
        topEdges.push([curr.node.node_name, toNode.node_name, 'cond-fan-out']);
      }
    } else if (curr.type === 'conditional' && next.type === 'single') {
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
    } else if (curr.type === 'parallel' && next.type === 'parallel') {
      for (const fromNode of curr.nodes) {
        for (const toNode of next.nodes) {
          topEdges.push([fromNode.node_name, toNode.node_name, 'fan-in']);
        }
      }
    } else {
      const fromNames = slotNodeNames(curr);
      const toNames = slotNodeNames(next);
      for (const from of fromNames) {
        for (const to of toNames) {
          topEdges.push([from, to, 'cond-fan-out']);
        }
      }
    }
  }

  // --- Pass 2: non-adjacent fan-in (multi-source merge points) ---
  // For each later single-node slot `S`, look at ALL earlier parallel-group
  // members and emit a fan-in edge from each member that could plausibly
  // point to `S`.  `isEdgeInTopology` in NodeGraph.tsx filters spurious spurs,
  // so over-approximation is safe and cheap.
  for (let j = 1; j < topSlots.length; j++) {
    const next = topSlots[j];
    if (next.type !== 'single') continue;
    const destName = next.node.node_name;
    for (let i = 0; i < j - 1; i++) {
      const curr = topSlots[i];
      if (curr.type === 'parallel') {
        for (const fromNode of curr.nodes) {
          topEdges.push([fromNode.node_name, destName, 'fan-in']);
        }
      } else if (curr.type === 'conditional') {
        for (const fromNode of curr.nodes) {
          topEdges.push([fromNode.node_name, destName, 'cond-fan-in']);
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

  // Shift positions down if any node extends above the top margin.
  // CENTER_Y is a fixed anchor; with many parallel nodes the top ones get
  // negative y-coordinates and are clipped by the SVG viewport.
  const MARGIN_TOP = NODE_RADIUS + 20;
  const allY = Object.values(positions).map(p => p.y);
  const minNodeY = allY.length > 0 ? Math.min(...allY) : CENTER_Y;
  const yOffset = Math.max(0, MARGIN_TOP - minNodeY);
  if (yOffset > 0) {
    for (const name of Object.keys(positions)) {
      positions[name] = { x: positions[name].x, y: positions[name].y + yOffset };
    }
    for (const [id, bubble] of bubbles.entries()) {
      bubbles.set(id, { ...bubble, y: bubble.y + yOffset });
    }
  }

  // Dynamic height: ensure the SVG is tall enough to show all nodes plus
  // their labels (NODE_RADIUS + ~30 px for label text and margin).
  const maxNodeY = allY.length > 0 ? Math.max(...allY) + yOffset : CENTER_Y;
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
