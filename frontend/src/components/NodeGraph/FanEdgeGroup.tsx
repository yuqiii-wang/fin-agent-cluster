import React from 'react';
import { COLOR_GRAPH_ARROW } from '../../constants/styleColors';

interface Point { x: number; y: number }

interface Props {
  /** Exactly one point for fan-out; N points for fan-in. */
  froms: Point[];
  /** N points for fan-out; exactly one for fan-in. */
  tos: Point[];
  fromR: number;
  toR: number;
  kind: 'fan-out' | 'fan-in';
  isHighlighted: boolean;
  onHoverChange: (hovered: boolean) => void;
}

/**
 * Renders a fan-out or fan-in edge group using orthogonal (right-angle) paths.
 *
 * Fan-out:   trunk → midX bus ─┬── spur → target1
 *                               ├── spur → target2
 *                               └── spur → target3
 *
 * Fan-in:  source1 spur ──┐
 *          source2 spur ──┤ midX bus → trunk → target
 *          source3 spur ──┘
 */
const FanEdgeGroup: React.FC<Props> = ({ froms, tos, fromR, toR, kind, isHighlighted, onHoverChange }) => {
  const stroke = isHighlighted ? '#ffffff' : COLOR_GRAPH_ARROW;
  const sw = isHighlighted ? 2 : 1.5;

  const commonLine = { stroke, strokeWidth: sw, fill: 'none' } as const;

  if (kind === 'fan-out') {
    const from = froms[0];
    // all tos share the same x in the parallel slot
    const toX = tos[0].x;
    const midX = (from.x + fromR + toX - toR) / 2;
    const minY = Math.min(...tos.map(t => t.y));
    const maxY = Math.max(...tos.map(t => t.y));

    return (
      <g onMouseEnter={() => onHoverChange(true)} onMouseLeave={() => onHoverChange(false)} style={{ cursor: 'pointer' }}>
        {/* trunk: source → midX */}
        <line x1={from.x + fromR} y1={from.y} x2={midX} y2={from.y} {...commonLine} />
        {/* bus: vertical spine at midX */}
        <line x1={midX} y1={minY} x2={midX} y2={maxY} {...commonLine} />
        {/* spurs: midX → each target, with arrowhead */}
        {tos.map((to, i) => (
          <line key={i}
            x1={midX} y1={to.y} x2={to.x - toR} y2={to.y}
            markerEnd="url(#arrow)"
            {...commonLine}
          />
        ))}
      </g>
    );
  }

  // fan-in
  const to = tos[0];
  // all froms share the same x in the parallel slot
  const fromX = froms[0].x;
  const midX = (fromX + fromR + to.x - toR) / 2;
  const minY = Math.min(...froms.map(f => f.y));
  const maxY = Math.max(...froms.map(f => f.y));

  return (
    <g onMouseEnter={() => onHoverChange(true)} onMouseLeave={() => onHoverChange(false)} style={{ cursor: 'pointer' }}>
      {/* spurs: each source → midX */}
      {froms.map((from, i) => (
        <line key={i}
          x1={from.x + fromR} y1={from.y} x2={midX} y2={from.y}
          {...commonLine}
        />
      ))}
      {/* bus: vertical spine at midX */}
      <line x1={midX} y1={minY} x2={midX} y2={maxY} {...commonLine} />
      {/* trunk: midX → target, with arrowhead */}
      <line
        x1={midX} y1={to.y} x2={to.x - toR} y2={to.y}
        markerEnd="url(#arrow)"
        {...commonLine}
      />
    </g>
  );
};

export default FanEdgeGroup;
