import React from 'react';
import { calcEdgePath } from './layout';
import type { EdgeKind } from './types';
import { COLOR_GRAPH_ARROW, COLOR_TEXT_DIM } from '../../constants/styleColors';

interface Props {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  fromR: number;
  toR: number;
  kind?: EdgeKind;
  isHighlighted?: boolean;
  onHoverChange?: (hovered: boolean) => void;
}

const KIND_STYLES: Record<EdgeKind, {
  stroke: string;
  strokeWidth: number;
  dashArray?: string;
  marker: string;
}> = {
  sequential:  { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)' },
  'fan-out':   { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)' }, // fallback; normally rendered by FanEdgeGroup
  'fan-in':    { stroke: COLOR_GRAPH_ARROW, strokeWidth: 2,   marker: 'url(#arrow)' }, // fallback; normally rendered by FanEdgeGroup
  conditional: { stroke: COLOR_TEXT_DIM,    strokeWidth: 1.5, marker: 'url(#arrow-hollow)', dashArray: '5 3' },
};

/** A single directed edge arrow between two nodes. */
const GraphEdge: React.FC<Props> = ({ id, from, to, fromR, toR, kind = 'sequential', isHighlighted, onHoverChange }) => {
  const d = calcEdgePath(from, to, fromR, toR);
  const s = KIND_STYLES[kind];
  return (
    <path
      key={id}
      d={d}
      stroke={isHighlighted ? '#ffffff' : s.stroke}
      strokeWidth={isHighlighted ? s.strokeWidth + 1.5 : s.strokeWidth}
      strokeDasharray={s.dashArray}
      fill="none"
      markerEnd={s.marker}
      style={{ cursor: 'pointer', transition: 'stroke 0.15s, stroke-width 0.15s' }}
      onMouseEnter={() => onHoverChange?.(true)}
      onMouseLeave={() => onHoverChange?.(false)}
    />
  );
};

export default GraphEdge;
