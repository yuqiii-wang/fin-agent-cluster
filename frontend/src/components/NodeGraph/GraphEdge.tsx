import React from 'react';
import { calcEdgePath, calcEdgeMidpoint } from './layout';
import type { EdgeKind } from './types';
import { COLOR_GRAPH_ARROW, COLOR_TEXT_DIM } from '../../constants/styleColors';

interface Props {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  fromR: number;
  toR: number;
  kind?: EdgeKind;
  /** Routing condition shown as a label when the edge is hovered. */
  conditionLabel?: string;
  isHighlighted?: boolean;
  onHoverChange?: (hovered: boolean) => void;
}

const KIND_STYLES: Record<EdgeKind, {
  stroke: string;
  strokeWidth: number;
  dashArray?: string;
  marker: string;
}> = {
  sequential:   { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)' },
  'fan-out':    { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)' }, // fallback; normally rendered by FanEdgeGroup
  'fan-in':     { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)' }, // fallback; normally rendered by FanEdgeGroup
  conditional:  { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)',  dashArray: '5 4' },
  'cond-fan-out': { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2, marker: 'url(#arrow)',  dashArray: '5 4' }, // fallback; normally rendered by FanEdgeGroup
  'cond-fan-in':  { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2, marker: 'url(#arrow)',  dashArray: '5 4' }, // fallback; normally rendered by FanEdgeGroup
};

/** A single directed edge arrow between two nodes. */
const GraphEdge: React.FC<Props> = ({ id, from, to, fromR, toR, kind = 'sequential', conditionLabel, isHighlighted, onHoverChange }) => {
  const d = calcEdgePath(from, to, fromR, toR);
  const s = KIND_STYLES[kind];
  const mid = (conditionLabel && isHighlighted) ? calcEdgeMidpoint(from, to, fromR, toR) : null;
  return (
    <g
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
      style={{ cursor: conditionLabel ? 'pointer' : undefined }}
    >
      <path
        key={id}
        d={d}
        stroke={isHighlighted ? '#ffffff' : s.stroke}
        strokeWidth={isHighlighted ? s.strokeWidth + 1.5 : s.strokeWidth}
        strokeDasharray={s.dashArray}
        fill="none"
        markerEnd={s.marker}
        style={{ transition: 'stroke 0.15s, stroke-width 0.15s' }}
      />
      {/* transparent wider hitbox for easier hover */}
      <path d={d} stroke="transparent" strokeWidth={10} fill="none" />
      {mid && conditionLabel && (
        <text x={mid.x} y={mid.y - 8} textAnchor="middle" fontSize={10} fill="#ffffff"
          style={{ pointerEvents: 'none' }}>
          {conditionLabel}
        </text>
      )}
    </g>
  );
};

export default GraphEdge;
