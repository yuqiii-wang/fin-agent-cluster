/**
 * NodeGraph — SVG-based LangGraph node topology visualiser.
 *
 * Visual rules:
 *  - Subgraph nodes → large circle (r=36)
 *  - Typical nodes  → small circle (r=22)
 *  - Inner nodes (parent_node_id set) → rendered inside a subgraph bubble
 *  - Node colour    → driven by work_status
 */

import React, { useMemo } from 'react';
import type { NodeInfo } from '../types';

const STATUS_COLORS: Record<string, string> = {
  pending:   '#8c8c8c',
  running:   '#1677ff',
  completed: '#52c41a',
  failed:    '#ff4d4f',
  cancelled: '#faad14',
  wrong:     '#d4380d',
};

function nodeColor(status: string): string {
  return STATUS_COLORS[status] ?? '#8c8c8c';
}

// Hard-coded topology positions for the known graph.
// Positions are relative inside the 800×500 canvas.
const TOPOLOGY: Record<string, { x: number; y: number }> = {
  // Top-level flow
  query_node:         { x: 120, y: 200 },
  research_subgraph:  { x: 380, y: 200 },
  conclusion_node:    { x: 660, y: 200 },
  // Inner nodes inside research_subgraph
  stats_node:         { x: 310, y: 185 },
  news_node:          { x: 380, y: 245 },
  merge_node:         { x: 450, y: 185 },
};

const SUBGRAPH_RADIUS = 36;
const NODE_RADIUS = 22;
const INNER_RADIUS = 14;

// Edges in the top-level graph (source → target node_names)
const EDGES: Array<[string, string]> = [
  ['query_node', 'research_subgraph'],
  ['research_subgraph', 'conclusion_node'],
];

// Edges inside the research_subgraph
const INNER_EDGES: Array<[string, string]> = [
  ['stats_node', 'merge_node'],
  ['news_node', 'merge_node'],
];

interface Props {
  nodes: NodeInfo[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

function calcEdgePath(
  from: { x: number; y: number },
  to: { x: number; y: number },
  fromR: number,
  toR: number,
): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const x1 = from.x + (dx / dist) * fromR;
  const y1 = from.y + (dy / dist) * fromR;
  const x2 = to.x - (dx / dist) * toR;
  const y2 = to.y - (dy / dist) * toR;
  return `M ${x1} ${y1} L ${x2} ${y2}`;
}

const NodeGraph: React.FC<Props> = ({ nodes, selectedNodeId, onSelectNode }) => {
  const nodeByName = useMemo(() => {
    const m: Record<string, NodeInfo> = {};
    for (const n of nodes) m[n.node_name] = n;
    return m;
  }, [nodes]);

  function getNodeRadius(name: string): number {
    const n = nodeByName[name];
    if (!n) return NODE_RADIUS;
    if (n.type === 'Subgraph') return SUBGRAPH_RADIUS;
    if (n.parent_node_id) return INNER_RADIUS;
    return NODE_RADIUS;
  }

  const SVG_W = 800;
  const SVG_H = 360;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      style={{ fontFamily: 'sans-serif', userSelect: 'none' }}
    >
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="#aaa" />
        </marker>
      </defs>

      {/* Top-level edges */}
      {EDGES.map(([from, to]) => {
        const fp = TOPOLOGY[from];
        const tp = TOPOLOGY[to];
        if (!fp || !tp) return null;
        const path = calcEdgePath(fp, tp, getNodeRadius(from), getNodeRadius(to));
        return (
          <path
            key={`${from}-${to}`}
            d={path}
            stroke="#aaa"
            strokeWidth={2}
            fill="none"
            markerEnd="url(#arrow)"
          />
        );
      })}

      {/* Inner edges inside subgraph */}
      {INNER_EDGES.map(([from, to]) => {
        const fp = TOPOLOGY[from];
        const tp = TOPOLOGY[to];
        if (!fp || !tp) return null;
        const path = calcEdgePath(fp, tp, getNodeRadius(from), getNodeRadius(to));
        return (
          <path
            key={`inner-${from}-${to}`}
            d={path}
            stroke="#aaa"
            strokeWidth={1.5}
            strokeDasharray="4 2"
            fill="none"
            markerEnd="url(#arrow)"
          />
        );
      })}

      {/* Subgraph background bubble */}
      {(() => {
        const sg = TOPOLOGY['research_subgraph'];
        if (!sg) return null;
        return (
          <ellipse
            cx={sg.x}
            cy={sg.y}
            rx={90}
            ry={55}
            fill="rgba(22,119,255,0.05)"
            stroke="rgba(22,119,255,0.3)"
            strokeWidth={1.5}
            strokeDasharray="6 3"
          />
        );
      })()}

      {/* Render all known nodes */}
      {Object.entries(TOPOLOGY).map(([name, pos]) => {
        const info = nodeByName[name];
        const isSubgraph = name === 'research_subgraph';
        const isInner = !!info?.parent_node_id;
        const r = isSubgraph ? SUBGRAPH_RADIUS : isInner ? INNER_RADIUS : NODE_RADIUS;
        const color = info ? nodeColor(info.status) : '#d9d9d9';
        const isSelected = info && info.node_id === selectedNodeId;
        const label = name.replace(/_/g, ' ');

        return (
          <g
            key={name}
            style={{ cursor: info ? 'pointer' : 'default' }}
            onClick={() => info && onSelectNode(info.node_id)}
          >
            <circle
              cx={pos.x}
              cy={pos.y}
              r={r}
              fill={color}
              fillOpacity={info ? 0.85 : 0.25}
              stroke={isSelected ? '#fff' : color}
              strokeWidth={isSelected ? 3 : 1.5}
              filter={isSelected ? 'drop-shadow(0 0 6px rgba(255,255,255,0.8))' : undefined}
            />
            {/* status pulse ring for running */}
            {info?.status === 'running' && (
              <circle
                cx={pos.x}
                cy={pos.y}
                r={r + 6}
                fill="none"
                stroke="#1677ff"
                strokeWidth={1.5}
                opacity={0.5}
              >
                <animate attributeName="r" values={`${r + 4};${r + 12};${r + 4}`} dur="1.5s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.6;0;0.6" dur="1.5s" repeatCount="indefinite" />
              </circle>
            )}
            {/* Label */}
            <text
              x={pos.x}
              y={pos.y + r + 14}
              textAnchor="middle"
              fontSize={isInner ? 9 : 11}
              fill="#e0e0e0"
              pointerEvents="none"
            >
              {label}
            </text>
            {/* Elapsed inside large nodes */}
            {!isInner && info && info.elapsed_ms > 0 && (
              <text
                x={pos.x}
                y={pos.y + 4}
                textAnchor="middle"
                fontSize={9}
                fill="#fff"
                pointerEvents="none"
              >
                {info.elapsed_ms < 1000 ? `${info.elapsed_ms}ms` : `${(info.elapsed_ms / 1000).toFixed(1)}s`}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
};

export default NodeGraph;
