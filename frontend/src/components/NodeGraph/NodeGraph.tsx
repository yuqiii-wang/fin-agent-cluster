/**
 * NodeGraph — SVG-based LangGraph node topology visualiser.
 *
 * Layout is computed dynamically from the nodes prop:
 *  - Top-level nodes (no parent_node_id) laid out left-to-right
 *  - Subgraph nodes with inner children: shown as a small collapsed square by default;
 *    click to expand to full bubble with inner nodes at normal size.
 *  - Nodes sharing the same parallel_group within a subgraph are stacked
 *    vertically (fan-out / fan-in pattern) at the same horizontal slot
 *  - Edges inferred from slot order: single→parallel fan-out, parallel→single fan-in
 */

import React, { useMemo, useState } from 'react';
import type { NodeInfo } from '../../types';
import type { GraphTopology } from '../../types';
import type { Bubble, EdgeKind } from './types';
import { SVG_H, INNER_RADIUS, NODE_RADIUS, SUBGRAPH_RADIUS, COLLAPSED_BUBBLE_SIZE, BUBBLE_RX } from './constants';
// SVG_H is kept as the minimum height for the empty-state placeholder
import { computeLayout } from './layout';
import SubgraphBubble from './SubgraphBubble';
import GraphEdge from './GraphEdge';
import FanEdgeGroup from './FanEdgeGroup';
import NodeCircle from './NodeCircle';
import InnerNode from './InnerNode';
import { COLOR_TEXT_SECONDARY } from '../../constants/styleColors';

type EdgeTuple = [string, string, EdgeKind];
type EdgeUnit =
  | { type: 'single'; from: string; to: string; kind: EdgeKind }
  | { type: 'fan'; froms: string[]; tos: string[]; kind: 'fan-out' | 'fan-in'; dashed?: boolean };

/** Group `topEdges` into logical rendering units.
 *
 * Rules (applied in order; each tuple consumed exactly once):
 *   1. Multiple edges sharing the SAME destination → a single `fan-in` unit.
 *      This is the right-angle bus pattern for merge nodes (e.g. `final_report`).
 *   2. Multiple edges sharing the SAME source → a single `fan-out` unit.
 *   3. Any remaining tuple → a `single` (straight-line) unit.
 *
 * Conditional fan variants are normalised to `fan-out`/`fan-in` for grouping;
 * the `dashed` flag is set on the unit instead so `FanEdgeGroup` can still
 * render conditionality when the runtime graph needs it.
 */
function groupEdges(edges: EdgeTuple[]): EdgeUnit[] {
  // Count outgoing / incoming edge cardinality so we can pick the dominant
  // grouping direction when a single edge could be assigned either way.
  const outDeg = new Map<string, number>();
  const inDeg = new Map<string, number>();
  for (const [from, to] of edges) {
    outDeg.set(from, (outDeg.get(from) ?? 0) + 1);
    inDeg.set(to, (inDeg.get(to) ?? 0) + 1);
  }

  const consumed = new Set<number>();
  const units: EdgeUnit[] = [];

  // 1. Group edges by destination (fan-in).  Iterate in first-seen order so
  //    `final_report` and its siblings are drawn in the order the topology
  //    declared them.
  const byDest = new Map<string, { indices: number[]; anyConditional: boolean }>();
  edges.forEach(([from, to, kind], i) => {
    // Fan-in eligible: an edge whose destination has more than one incoming edge.
    // Also accept explicitly-marked fan-in / cond-fan-in tuples even when the
    // destination otherwise looks single-input (keeps backend intent intact).
    const eligible =
      (inDeg.get(to) ?? 0) > 1 ||
      kind === 'fan-in' ||
      kind === 'cond-fan-in';
    if (!eligible) return;
    const bucket = byDest.get(to) ?? { indices: [], anyConditional: false };
    bucket.indices.push(i);
    if (kind === 'cond-fan-in' || kind === 'conditional') bucket.anyConditional = true;
    byDest.set(to, bucket);
  });

  // Emit fan-in groups, marking each participating edge index consumed.  Only
  // actually emit a *group* when there is more than one participating edge;
  // single-participant entries fall through to the later passes so simple
  // sequential edges keep their straight-line rendering.
  const destOrder: string[] = [];
  const seenDest = new Set<string>();
  for (const [, to] of edges) {
    if (!seenDest.has(to)) {
      seenDest.add(to);
      destOrder.push(to);
    }
  }
  for (const dest of destOrder) {
    const bucket = byDest.get(dest);
    if (!bucket || bucket.indices.length < 2) continue;
    bucket.indices.forEach(i => consumed.add(i));
    const froms = bucket.indices
      .map(i => edges[i][0])
      // Preserve declaration order, but deduplicate so the visual bus isn't
      // crowded with duplicate spurs when the layout over-declares them.
      .filter((name, idx, arr) => arr.indexOf(name) === idx);
    units.push({
      type: 'fan',
      froms,
      tos: [dest],
      kind: 'fan-in',
      dashed: bucket.anyConditional,
    });
  }

  // 2. Group remaining edges by source (fan-out).
  const bySource = new Map<string, { indices: number[]; anyConditional: boolean }>();
  edges.forEach(([from, to, kind], i) => {
    if (consumed.has(i)) return;
    const eligible =
      (outDeg.get(from) ?? 0) > 1 ||
      kind === 'fan-out' ||
      kind === 'cond-fan-out';
    if (!eligible) return;
    const bucket = bySource.get(from) ?? { indices: [], anyConditional: false };
    bucket.indices.push(i);
    if (kind === 'cond-fan-out' || kind === 'conditional') bucket.anyConditional = true;
    bySource.set(from, bucket);
  });

  const sourceOrder: string[] = [];
  const seenSource = new Set<string>();
  for (const [from] of edges) {
    if (!seenSource.has(from)) {
      seenSource.add(from);
      sourceOrder.push(from);
    }
  }
  for (const src of sourceOrder) {
    const bucket = bySource.get(src);
    if (!bucket || bucket.indices.length < 2) continue;
    bucket.indices.forEach(i => consumed.add(i));
    const tos = bucket.indices
      .map(i => edges[i][1])
      .filter((name, idx, arr) => arr.indexOf(name) === idx);
    units.push({
      type: 'fan',
      froms: [src],
      tos,
      kind: 'fan-out',
      dashed: bucket.anyConditional,
    });
  }

  // 3. Everything else — render as a single (straight-line) edge.
  for (let i = 0; i < edges.length; i++) {
    if (consumed.has(i)) continue;
    const [from, to, kind] = edges[i];
    units.push({ type: 'single', from, to, kind });
  }

  return units;
}

interface Props {
  nodes: NodeInfo[];
  topology?: GraphTopology | null;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

const NodeGraph: React.FC<Props> = ({ nodes, topology, selectedNodeId, onSelectNode }) => {
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);

  /** keyed by "fromNode→toNode", value is the condition_label */
  const edgeConditionLabels = useMemo(() => {
    const m = new Map<string, string>();
    if (!topology) return m;
    for (const e of topology.edges) {
      if (e.condition_label) m.set(`${e.from_node}→${e.to_node}`, e.condition_label);
    }
    return m;
  }, [topology]);

  /** Set of "from→to" pairs that are declared in the topology (used to filter
   *  fan-out/fan-in spurs so only real edges get drawn). */
  const topologyEdgeSet = useMemo(() => {
    const s = new Set<string>();
    if (!topology) return s;
    for (const e of topology.edges) s.add(`${e.from_node}→${e.to_node}`);
    return s;
  }, [topology]);

  /** Returns true if `fromName→toName` is explicitly declared in the topology.
   *  When no topology is available (legacy paths), returns true so all inferred
   *  spurs are drawn as before. */
  const isEdgeInTopology = useMemo(() => {
    if (!topology || topology.edges.length === 0) {
      return (_from: string, _to: string) => true;
    }
    return (fromName: string, toName: string) =>
      topologyEdgeSet.has(`${fromName}→${toName}`);
  }, [topology, topologyEdgeSet]);

  const nodeByName = useMemo(() => {
    const m: Record<string, NodeInfo> = {};
    for (const n of nodes) m[n.node_name] = n;
    return m;
  }, [nodes]);

  /** Nodes whose status is failed/wrong/cancelled do not forward edges —
   *  their downstream "output" never ran and should not be rendered. */
  const BAD_STATUSES = new Set(['failed', 'wrong', 'cancelled']);
  const nodeProducesEdges = useMemo(() => {
    return (nodeName: string) => {
      const n = nodeByName[nodeName];
      if (!n) return false;
      if (n.is_topology_only) return false;
      if (BAD_STATUSES.has(n.status)) return false;
      return true;
    };
  }, [nodeByName]);

  /**
   * A subgraph is expanded when it is the selected node, or when any of its
   * direct children is the selected node.
   */
  const expandedSubgraphIds = useMemo(() => {
    const set = new Set<string>();
    if (!selectedNodeId) return set;
    for (const n of nodes) {
      if (n.node_id === selectedNodeId && nodes.some(c => c.parent_node_id === n.node_id)) {
        set.add(n.node_id);
      }
      if (n.parent_node_id && n.node_id === selectedNodeId) {
        set.add(n.parent_node_id);
      }
    }
    return set;
  }, [nodes, selectedNodeId]);

  const layout = useMemo(() => computeLayout(nodes, expandedSubgraphIds), [nodes, expandedSubgraphIds]);
  const { positions, svgW, svgH, topLevel, innerByParentId, topEdges, innerEdges, bubbles } = layout;

  /** Collapsed display bubble: a square centered at the full bubble's centre. */
  function collapsedBubble(bubble: Bubble): Bubble {
    const cx = bubble.x + bubble.w / 2;
    const cy = bubble.y + bubble.h / 2;
    const S = COLLAPSED_BUBBLE_SIZE;
    return { x: cx - S / 2, y: cy - S / 2, w: S, h: S };
  }

  /** SVG transform that shrinks full-bubble coordinates into the collapsed square. */
  function collapseTransform(bubble: Bubble): string {
    const cx = bubble.x + bubble.w / 2;
    const cy = bubble.y + bubble.h / 2;
    const s = COLLAPSED_BUBBLE_SIZE / Math.max(bubble.w, bubble.h);
    return `translate(${cx},${cy}) scale(${s}) translate(${-cx},${-cy})`;
  }

  function effectiveRadius(nodeName: string): number {
    const n = nodeByName[nodeName];
    if (!n) return NODE_RADIUS;
    const bubble = bubbles.get(n.node_id);
    if (bubble) return expandedSubgraphIds.has(n.node_id) ? bubble.w / 2 : COLLAPSED_BUBBLE_SIZE / 2;
    if (n.type === 'Subgraph') return SUBGRAPH_RADIUS;
    return NODE_RADIUS;
  }

  if (nodes.length === 0) {
    return (
      <svg width="100%" height={SVG_H} style={{ display: 'block' }}>
        <text x="50%" y="50%" textAnchor="middle" fontSize={12} fill={COLOR_TEXT_SECONDARY}>
          No nodes yet.
        </text>
      </svg>
    );
  }

  return (
    <div style={{ width: '100%', overflowX: 'auto', overflowY: 'auto' }}>
    <svg
      width="100%"
      height={svgH}
      viewBox={`0 0 ${svgW} ${svgH}`}
      preserveAspectRatio="xMidYMid meet"
      style={{ display: 'block', fontFamily: 'sans-serif', userSelect: 'none' }}
    >
      <defs>
        <marker id="arrow" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto">
          <path d="M0,0 L0,5 L5,2.5 z" fill="context-stroke" />
        </marker>
        <marker id="arrow-hollow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0.5 L0,5.5 L5.5,3 z" fill="none" stroke="context-stroke" strokeWidth="1.2" />
        </marker>
        {/* Clip paths for subgraph inner content */}
        {topLevel.map(n => {
          const bubble = bubbles.get(n.node_id);
          if (!bubble) return null;
          const expanded = expandedSubgraphIds.has(n.node_id);
          const display = expanded ? bubble : collapsedBubble(bubble);
          return (
            <clipPath key={`clip-${n.node_id}`} id={`clip-${n.node_id}`}>
              <rect x={display.x} y={display.y} width={display.w} height={display.h} rx={BUBBLE_RX} />
            </clipPath>
          );
        })}
      </defs>

      {/* Pass 1 — subgraph bubble backgrounds */}
      {topLevel.map(n => {
        const bubble = bubbles.get(n.node_id);
        if (!bubble) return null;
        const expanded = expandedSubgraphIds.has(n.node_id);
        return (
          <SubgraphBubble
            key={`bubble-${n.node_id}`}
            node={n}
            bubble={expanded ? bubble : collapsedBubble(bubble)}
            isSelected={expanded}
            onSelect={() => onSelectNode(n.node_id)}
          />
        );
      })}

      {/* Pass 2 — top-level chain edges (sequential, fan-out/in, or conditional dashed fan)
           Only draw edges whose source node actually ran successfully:
             - topology-only placeholders are pending upstream execution
             - `failed` / `wrong` / `cancelled` nodes never produced downstream output
           For fan-out/fan-in groups, only spurs declared in `topology.edges` are drawn so
           partial fan-patterns (e.g. only prepare_peers→load_peers_stats inside a larger
           parallel group) render correctly instead of spurious spurs from every sibling. */}
      {groupEdges(topEdges.filter(([from]) => nodeProducesEdges(from))).map((unit, ui) => {
        if (unit.type === 'single') {
          if (!isEdgeInTopology(unit.from, unit.to)) return null;
          const fp = positions[unit.from];
          const tp = positions[unit.to];
          if (!fp || !tp) return null;
          const edgeId = `edge-${unit.from}-${unit.to}`;
          return (
            <GraphEdge
              key={edgeId}
              id={edgeId}
              from={fp} to={tp}
              fromR={effectiveRadius(unit.from)}
              toR={effectiveRadius(unit.to)}
              kind={unit.kind}
              conditionLabel={edgeConditionLabels.get(`${unit.from}→${unit.to}`)}
              isHighlighted={hoveredEdgeId === edgeId}
              onHoverChange={h => setHoveredEdgeId(h ? edgeId : null)}
            />
          );
        }
        // Filter fan spurs against topology edges so only declared edges are drawn.
        const filteredFroms = unit.froms.filter(fn =>
          unit.tos.some(tn => isEdgeInTopology(fn, tn)));
        const filteredTos = unit.tos.filter(tn =>
          unit.froms.some(fn => isEdgeInTopology(fn, tn)));
        const froms = filteredFroms.map(n => positions[n]).filter((p): p is { x: number; y: number } => !!p);
        const tos   = filteredTos.map(n => positions[n]).filter((p): p is { x: number; y: number } => !!p);
        if (froms.length === 0 || tos.length === 0) return null;
        const fanId = `top-fan-${ui}`;
        // For conditional fans, dash each section based on whether its nearest node ran.
        // Runtime nodes have is_topology_only=undefined (only set to true for topology-only nodes),
        // so default to false (solid) when node is in map, true (dashed) when absent.
        const spurDashed = (name: string) => {
          const node = nodeByName[name];
          return node ? (node.is_topology_only ?? false) : true;
        };
        const dashedSpurs = unit.dashed
          ? unit.kind === 'fan-out'
            ? filteredTos.map(spurDashed)
            : filteredFroms.map(spurDashed)
          : undefined;
        const trunkDashed = unit.dashed
          ? (unit.kind === 'fan-out'
              ? spurDashed(filteredFroms[0])
              : spurDashed(filteredTos[0]))
          : false;
        // Per-spur condition labels: for fan-out keyed by each to-node; for fan-in keyed by each from-node
        const conditionLabels = unit.kind === 'fan-out'
          ? filteredTos.map(toName => edgeConditionLabels.get(`${filteredFroms[0]}→${toName}`))
          : filteredFroms.map(fromName => edgeConditionLabels.get(`${fromName}→${filteredTos[0]}`));
        return (
          <FanEdgeGroup
            key={fanId}
            froms={froms}
            tos={tos}
            fromR={effectiveRadius(filteredFroms[0])}
            toR={effectiveRadius(filteredTos[0])}
            kind={unit.kind}
            dashedSpurs={dashedSpurs}
            trunkDashed={trunkDashed}
            conditionLabels={conditionLabels}
          />
        );
      })}

      {/* Pass 3 — inner edges per subgraph (scaled + clipped when collapsed; hover active when expanded)
           Same failure-gating as top-level: subgraph edges are hidden when a source node never ran. */}
      {Array.from(innerEdges.entries()).map(([parentId, edges]) => {
        const bubble = bubbles.get(parentId);
        const expanded = !bubble || expandedSubgraphIds.has(parentId);
        const transform = bubble && !expanded ? collapseTransform(bubble) : undefined;
        return (
          <g
            key={`ie-${parentId}`}
            transform={transform}
            clipPath={bubble ? `url(#clip-${parentId})` : undefined}
            style={{ pointerEvents: expanded ? undefined : 'none' }}
          >
            {groupEdges(edges.filter(([from]) => nodeProducesEdges(from))).map((unit, ui) => {
              if (unit.type === 'single') {
                const fp = positions[unit.from];
                const tp = positions[unit.to];
                if (!fp || !tp) return null;
                const edgeId = `ie-${parentId}-${unit.from}-${unit.to}`;
                return (
                  <GraphEdge
                    key={edgeId}
                    id={edgeId}
                    from={fp} to={tp}
                    fromR={INNER_RADIUS}
                    toR={INNER_RADIUS}
                    kind={unit.kind}
                    isHighlighted={hoveredEdgeId === edgeId}
                    onHoverChange={h => setHoveredEdgeId(h ? edgeId : null)}
                  />
                );
              }
              const froms = unit.froms.map(n => positions[n]).filter((p): p is { x: number; y: number } => !!p);
              const tos   = unit.tos.map(n => positions[n]).filter((p): p is { x: number; y: number } => !!p);
              if (froms.length === 0 || tos.length === 0) return null;
              const fanId = `fan-${parentId}-${ui}`;
              return (
                <FanEdgeGroup
                  key={fanId}
                  froms={froms}
                  tos={tos}
                  fromR={INNER_RADIUS}
                  toR={INNER_RADIUS}
                  kind={unit.kind}
                />
              );
            })}
          </g>
        );
      })}

      {/* Pass 4a — top-level regular node circles (non-subgraph) */}
      {topLevel.map(n => {
        if (bubbles.has(n.node_id)) return null;
        const pos = positions[n.node_name];
        if (!pos) return null;
        return (
          <NodeCircle
            key={n.node_id}
            node={n}
            pos={pos}
            isSelected={n.node_id === selectedNodeId}
            onSelect={() => onSelectNode(n.node_id)}
          />
        );
      })}

      {/* Pass 4b — inner nodes per subgraph (scaled + clipped when collapsed; events disabled) */}
      {Array.from(innerByParentId.entries()).map(([parentId, children]) => {
        const bubble = bubbles.get(parentId);
        const expanded = !bubble || expandedSubgraphIds.has(parentId);
        const transform = bubble && !expanded ? collapseTransform(bubble) : undefined;
        return (
          <g
            key={`in-${parentId}`}
            transform={transform}
            clipPath={bubble ? `url(#clip-${parentId})` : undefined}
            style={{ pointerEvents: expanded ? undefined : 'none' }}
          >
            {children.map(n => {
              const pos = positions[n.node_name];
              if (!pos) return null;
              return (
                <InnerNode
                  key={n.node_id}
                  node={n}
                  pos={pos}
                  isSelected={n.node_id === selectedNodeId}
                  onSelect={e => { e.stopPropagation(); onSelectNode(n.node_id); }}
                />
              );
            })}
          </g>
        );
      })}
    </svg>
    </div>
  );
};

export default NodeGraph;
