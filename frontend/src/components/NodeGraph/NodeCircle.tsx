import React from 'react';
import type { NodeInfo } from '../../types';
import { NODE_RADIUS, SUBGRAPH_RADIUS } from './constants';
import { nodeColor } from './utils';
import {
  COLOR_GRAPH_FALLBACK_NODE, COLOR_GRAPH_RUNNING_RING,
  COLOR_GRAPH_SELECTED_RING, COLOR_GRAPH_SELECTED_GLOW,
  COLOR_GRAPH_LABEL_TEXT, COLOR_GRAPH_ELAPSED_TEXT,
} from '../../constants/styleColors';

interface Props {
  node: NodeInfo;
  pos: { x: number; y: number };
  isSelected: boolean;
  onSelect: () => void;
}

/** Circle representing a top-level (non-subgraph-child) node. */
const NodeCircle: React.FC<Props> = ({ node, pos, isSelected, onSelect }) => {
  const r = node.type === 'Subgraph' ? SUBGRAPH_RADIUS : NODE_RADIUS;
  const color = nodeColor(node.status) ?? COLOR_GRAPH_FALLBACK_NODE;
  const label = node.node_name.replace(/_/g, ' ');

  return (
    <g style={{ cursor: 'pointer' }} onClick={onSelect}>
      <circle
        cx={pos.x} cy={pos.y} r={r}
        fill={color} fillOpacity={0.85}
        stroke={isSelected ? COLOR_GRAPH_SELECTED_RING : color}
        strokeWidth={isSelected ? 3 : 1.5}
        filter={isSelected ? `drop-shadow(0 0 6px ${COLOR_GRAPH_SELECTED_GLOW})` : undefined}
      />
      {node.status === 'running' && (
        <circle cx={pos.x} cy={pos.y} r={r + 6} fill="none"
          stroke={COLOR_GRAPH_RUNNING_RING} strokeWidth={1.5} opacity={0.5}>
          <animate attributeName="r" values={`${r+4};${r+12};${r+4}`} dur="1.5s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.6;0;0.6" dur="1.5s" repeatCount="indefinite" />
        </circle>
      )}
      <text x={pos.x} y={pos.y + r + 14} textAnchor="middle" fontSize={11}
        fill={COLOR_GRAPH_LABEL_TEXT} pointerEvents="none">
        {label}
      </text>
      {node.elapsed_ms > 0 && (
        <text x={pos.x} y={pos.y + 4} textAnchor="middle" fontSize={9}
          fill={COLOR_GRAPH_ELAPSED_TEXT} pointerEvents="none">
          {node.elapsed_ms < 1000 ? `${node.elapsed_ms}ms` : `${(node.elapsed_ms / 1000).toFixed(1)}s`}
        </text>
      )}
    </g>
  );
};

export default NodeCircle;
