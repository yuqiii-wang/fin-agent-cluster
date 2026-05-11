import React from 'react';
import type { NodeInfo } from '../../types';
import type { Bubble } from './types';
import { BUBBLE_RX } from './constants';
import {
  COLOR_GRAPH_SUBGRAPH_FILL, COLOR_GRAPH_SUBGRAPH_STROKE,
  COLOR_GRAPH_SELECTED_RING, COLOR_GRAPH_SELECTED_GLOW,
  COLOR_GRAPH_LABEL_TEXT,
} from '../../constants/styleColors';

interface Props {
  node: NodeInfo;
  bubble: Bubble;
  isSelected: boolean;
  onSelect: () => void;
}

/** Dashed bubble that represents a subgraph and wraps its inner nodes. */
const SubgraphBubble: React.FC<Props> = ({ node, bubble, isSelected, onSelect }) => (
  <g style={{ cursor: 'pointer' }} onClick={onSelect}>
    <rect
      x={bubble.x} y={bubble.y} width={bubble.w} height={bubble.h}
      rx={BUBBLE_RX}
      fill={COLOR_GRAPH_SUBGRAPH_FILL}
      stroke={isSelected ? COLOR_GRAPH_SELECTED_RING : COLOR_GRAPH_SUBGRAPH_STROKE}
      strokeWidth={isSelected ? 2 : 1.5}
      strokeDasharray="6 3"
      filter={isSelected ? `drop-shadow(0 0 5px ${COLOR_GRAPH_SELECTED_GLOW})` : undefined}
    />
    <text
      x={bubble.x + bubble.w / 2}
      y={bubble.y - 6}
      textAnchor="middle"
      fontSize={11}
      fill={COLOR_GRAPH_LABEL_TEXT}
      pointerEvents="none"
    >
      {node.node_name.replace(/_/g, ' ')}
    </text>
  </g>
);

export default SubgraphBubble;
