import React from 'react';
import type { NodeInfo } from '../../types';
import { INNER_RADIUS } from './constants';
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
  onSelect: (e: React.MouseEvent) => void;
}

/** Smaller circle for nodes nested inside a subgraph bubble. */
const InnerNode: React.FC<Props> = ({ node, pos, isSelected, onSelect }) => {
  const color = nodeColor(node.status) ?? COLOR_GRAPH_FALLBACK_NODE;
  const label = node.node_name.replace(/_/g, ' ');

  return (
    <g style={{ cursor: 'pointer' }} onClick={onSelect}>
      <circle
        cx={pos.x} cy={pos.y} r={INNER_RADIUS}
        fill={color} fillOpacity={0.85}
        stroke={isSelected ? COLOR_GRAPH_SELECTED_RING : color}
        strokeWidth={isSelected ? 2.5 : 1.5}
        filter={isSelected ? `drop-shadow(0 0 4px ${COLOR_GRAPH_SELECTED_GLOW})` : undefined}
      />
      {node.status === 'running' && (
        <circle cx={pos.x} cy={pos.y} r={INNER_RADIUS + 4} fill="none"
          stroke={COLOR_GRAPH_RUNNING_RING} strokeWidth={1} opacity={0.5}>
          <animate attributeName="r" values={`${INNER_RADIUS+3};${INNER_RADIUS+8};${INNER_RADIUS+3}`} dur="1.5s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.6;0;0.6" dur="1.5s" repeatCount="indefinite" />
        </circle>
      )}
      <text x={pos.x} y={pos.y + INNER_RADIUS + 11} textAnchor="middle" fontSize={9}
        fill={COLOR_GRAPH_LABEL_TEXT} pointerEvents="none">
        {label}
      </text>
      {node.elapsed_ms > 0 && (
        <text x={pos.x} y={pos.y + 3} textAnchor="middle" fontSize={7}
          fill={COLOR_GRAPH_ELAPSED_TEXT} pointerEvents="none">
          {node.elapsed_ms < 1000 ? `${node.elapsed_ms}ms` : `${(node.elapsed_ms / 1000).toFixed(1)}s`}
        </text>
      )}
    </g>
  );
};

export default InnerNode;
