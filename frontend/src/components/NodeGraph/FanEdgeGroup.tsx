import React, { useState } from 'react';
import { COLOR_GRAPH_ARROW } from '../../constants/styleColors';
import { NODE_RADIUS } from './constants';

interface Point { x: number; y: number }

interface Props {
  /** Exactly one point for fan-out; N points for fan-in. */
  froms: Point[];
  /** N points for fan-out; exactly one for fan-in. */
  tos: Point[];
  fromR: number;
  toR: number;
  kind: 'fan-out' | 'fan-in';
  /**
   * Per-spur dashing based on execution: for fan-out indexed by `tos`; for fan-in indexed by `froms`.
   * True = that node did not run (topology-only).
   */
  dashedSpurs?: boolean[];
  /**
   * Whether the trunk's directly-attached node did not run (topology-only).
   * Fan-out: source node; fan-in: destination node.
   * Defaults to false (solid).
   */
  trunkDashed?: boolean;
  /**
   * Per-spur condition label shown as an SVG text on hover.
   * For fan-out indexed by `tos`; for fan-in indexed by `froms`.
   */
  conditionLabels?: (string | undefined)[];
}

/**
 * Renders a fan-out or fan-in edge group using orthogonal (right-angle) paths.
 *
 * Geometry rule: the vertical bus sits at a fixed fraction of the horizontal gap
 * between the "near" and "far" sides.  Using phi ≈ 0.618 (the golden ratio) as the
 * long-leg fraction keeps both the horizontal stem and the bus visually balanced —
 * neither disappears into its adjacent node nor crowds the arrow tail:
 *
 *   Fan-out (fork): bus is placed ~38% of the gap away from the source
 *     ─→ short leg = 0.382 × gap  (source → bus);  long leg = 0.618 × gap (bus → dests)
 *
 *   Fan-in (merge): bus is placed ~38% of the gap away from the destination
 *     ─→ long leg = 0.618 × gap  (sources → bus); short leg = 0.382 × gap (bus → dest)
 *
 * This ratio is independent of the number of spurs, so a fan-in with sources at
 * different x positions (e.g. one source in an earlier slot) still renders
 * symmetrically.
 */
const FanEdgeGroup: React.FC<Props> = ({ froms, tos, fromR, toR, kind, dashedSpurs, trunkDashed = false, conditionLabels }) => {
  const [hoveredSpur, setHoveredSpur] = useState<number | null>(null);

  // Trunk/bus highlights when any spur is hovered
  const trunkActive = hoveredSpur !== null;

  // Golden-ratio split: long leg ≈ 0.618, short leg ≈ 0.382.
  // The bus sits on the short-leg side of the gap so the long leg has room to
  // breathe, and the arrow tail on the short leg remains crisp.
  const SHORT_LEG_RATIO = 0.382;

  function lineStyle(highlighted: boolean, dashed: boolean) {
    return {
      stroke: highlighted ? '#ffffff' : COLOR_GRAPH_ARROW,
      strokeWidth: highlighted ? 2 : 1.5,
      fill: 'none' as const,
      strokeDasharray: dashed ? '5 4' : undefined,
    };
  }

  /**
   * Renders the vertical bus as per-adjacent-pair segments.
   * Each segment is dashed only when BOTH its endpoint spurs did not run.
   * `points` is an array of { y, dashed } sorted by Y.
   */
  function busSegments(x: number, points: { y: number; dashed: boolean }[]) {
    return points.slice(0, -1).map((pt, i) => {
      const next = points[i + 1];
      const segDashed = pt.dashed && next.dashed;
      return (
        <line key={`bus-${i}`} x1={x} y1={pt.y} x2={x} y2={next.y}
          {...lineStyle(trunkActive, segDashed)}
          style={{ pointerEvents: 'none' }}
        />
      );
    });
  }

  if (kind === 'fan-out') {
    const from = froms[0];
    // Place the bus 38% into the gap, measured from the *source* side.
    // This gives the horizontal stem (source → bus) ~38% and each spur tail
    // (bus → dest) ~62% of the horizontal space — visually balanced.
    const nearestDestX = Math.min(...tos.map(t => t.x));
    const gap = (nearestDestX - toR) - (from.x + fromR);
    const busX = from.x + fromR + Math.max(gap * SHORT_LEG_RATIO, NODE_RADIUS + 16);

    const busPts = tos
      .map((t, i) => ({ y: t.y, dashed: dashedSpurs?.[i] ?? false }))
      .sort((a, b) => a.y - b.y);

    return (
      <g>
        {/* section1: source → busX (solid if source ran) */}
        <line x1={from.x + fromR} y1={from.y} x2={busX} y2={from.y} {...lineStyle(trunkActive, trunkDashed)} />
        {/* section2: vertical bus segments */}
        <line x1={busX} y1={from.y} x2={busX} y2={from.y} {...lineStyle(trunkActive, trunkDashed)} />
        {busSegments(busX, busPts)}
        {/* section3 per dest: bus → dest[i] (solid if dest[i] ran) */}
        {tos.map((to, i) => {
          const spurDashed = dashedSpurs?.[i] ?? false;
          const active = hoveredSpur === i;
          const label = conditionLabels?.[i];
          const labelX = (busX + to.x - toR) / 2;
          const labelY = to.y - 8;
          return (
            <g key={i}
              onMouseEnter={() => setHoveredSpur(i)}
              onMouseLeave={() => setHoveredSpur(null)}
              style={{ cursor: 'pointer' }}
            >
              <line x1={busX} y1={to.y} x2={to.x - toR} y2={to.y} markerEnd="url(#arrow)" {...lineStyle(active, spurDashed)} />
              {/* transparent hitbox */}
              <line x1={busX + 2} y1={to.y} x2={to.x - toR} y2={to.y} stroke="transparent" strokeWidth={8} />
              {active && label && (
                <text x={labelX} y={labelY} textAnchor="middle" fontSize={10} fill="#ffffff"
                  style={{ pointerEvents: 'none' }}>
                  {label}
                </text>
              )}
            </g>
          );
        })}
      </g>
    );
  }

  // fan-in: sources may live at DIFFERENT x positions.
  // Place the bus 38% into the gap *from the destination side* so the final
  // horizontal trunk into the destination (which carries the arrow marker) is
  // short and crisp, while each source has a long enough horizontal spur to
  // feel like a proper stem rather than a 1-px stub.
  const to = tos[0];
  const farthestSourceX = Math.max(...froms.map(f => f.x));
  const gap = (to.x - toR) - (farthestSourceX + fromR);
  // shortLeg = bus → dest; longLeg = sources → bus.
  const shortLeg = Math.max(gap * SHORT_LEG_RATIO, NODE_RADIUS + 16);
  const busX = to.x - toR - shortLeg;

  const trunks = [
    ...froms.map((f, i) => ({ y: f.y, dashed: dashedSpurs?.[i] ?? false })),
    { y: to.y, dashed: trunkDashed },
  ].sort((a, b) => a.y - b.y);

  return (
    <g>
      {/* section1 per source: source[i] → busX at source[i].y.  Each spur is
          independently hoverable so the user can inspect condition labels. */}
      {froms.map((from, i) => {
        const spurDashed = dashedSpurs?.[i] ?? false;
        const active = hoveredSpur === i;
        const label = conditionLabels?.[i];
        const labelX = (from.x + fromR + busX) / 2;
        const labelY = from.y - 8;
        return (
          <g key={i}
            onMouseEnter={() => setHoveredSpur(i)}
            onMouseLeave={() => setHoveredSpur(null)}
            style={{ cursor: 'pointer' }}
          >
            <line x1={from.x + fromR} y1={from.y} x2={busX} y2={from.y} {...lineStyle(active, spurDashed)} />
            {/* transparent hitbox — ends 2px before bus so bus area stays non-interactive */}
            <line x1={from.x + fromR} y1={from.y} x2={busX - 2} y2={from.y} stroke="transparent" strokeWidth={8} />
            {active && label && (
              <text x={labelX} y={labelY} textAnchor="middle" fontSize={10} fill="#ffffff"
                style={{ pointerEvents: 'none' }}>
                {label}
              </text>
            )}
          </g>
        );
      })}
      {/* section2: vertical bus segments — dashed per segment based on whether BOTH endpoints are dashed */}
      {busSegments(busX, trunks)}
      {/* section3: bus → dest — solid if dest ran */}
      <line
        x1={busX} y1={to.y} x2={to.x - toR} y2={to.y}
        markerEnd="url(#arrow)"
        {...lineStyle(trunkActive, trunkDashed)}
      />
    </g>
  );
};

export default FanEdgeGroup;
