import React, { useState } from 'react';
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
 * Three sections per logical edge — dashing driven entirely by execution state:
 *
 * Fan-out (fork):
 *   section1: source → bus  (solid if source ran)
 *   section2: vertical bus  (solid if any dest ran)
 *   section3: bus → dest[i] (solid if dest[i] ran)
 *
 * Fan-in (merge):
 *   section1+2: source[i] → bus (solid if source[i] ran)
 *   section2:   vertical bus    (solid if any source ran)
 *   section3:   bus → dest      (solid if dest ran)
 *
 * Mouse hover highlights the hovered spur + the shared trunk (white stroke),
 * but never changes the solid/dashed state.
 */
const FanEdgeGroup: React.FC<Props> = ({ froms, tos, fromR, toR, kind, dashedSpurs, trunkDashed = false, conditionLabels }) => {
  const [hoveredSpur, setHoveredSpur] = useState<number | null>(null);

  // Trunk/bus highlights when any spur is hovered
  const trunkActive = hoveredSpur !== null;

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
    const toX = tos[0].x;
    const midX = (from.x + fromR + toX - toR) / 2;

    const busPts = tos
      .map((t, i) => ({ y: t.y, dashed: dashedSpurs?.[i] ?? false }))
      .sort((a, b) => a.y - b.y);

    return (
      <g>
        {/* section1: source → midX — solid if source ran */}
        <line x1={from.x + fromR} y1={from.y} x2={midX} y2={from.y} {...lineStyle(trunkActive, trunkDashed)} />
        {/* section2: bus segments — each dashed only when both adjacent spurs did not run */}
        {busSegments(midX, busPts)}
        {/* section3 per dest: bus → dest[i] — solid if dest[i] ran; independently hoverable */}
        {tos.map((to, i) => {
          const spurDashed = dashedSpurs?.[i] ?? false;
          const active = hoveredSpur === i;
          const label = conditionLabels?.[i];
          const labelX = (midX + to.x - toR) / 2;
          const labelY = to.y - 8;
          return (
            <g key={i}
              onMouseEnter={() => setHoveredSpur(i)}
              onMouseLeave={() => setHoveredSpur(null)}
              style={{ cursor: 'pointer' }}
            >
              <line x1={midX} y1={to.y} x2={to.x - toR} y2={to.y} markerEnd="url(#arrow)" {...lineStyle(active, spurDashed)} />
              {/* transparent hitbox — starts 2px past bus so bus area stays non-interactive */}
              <line x1={midX + 2} y1={to.y} x2={to.x - toR} y2={to.y} stroke="transparent" strokeWidth={8} />
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

  // fan-in
  const to = tos[0];
  const fromX = froms[0].x;
  const midX = (fromX + fromR + to.x - toR) / 2;

  // Include to.y as a bus anchor so the vertical bus always reaches the trunk
  // start point even when there is only a single source spur.
  const busPts = [
    ...froms.map((f, i) => ({ y: f.y, dashed: dashedSpurs?.[i] ?? false })),
    { y: to.y, dashed: trunkDashed },
  ].sort((a, b) => a.y - b.y);

  return (
    <g>
      {/* section1+2 per source: source → midX — solid if source ran; independently hoverable */}
      {froms.map((from, i) => {
        const spurDashed = dashedSpurs?.[i] ?? false;
        const active = hoveredSpur === i;
        const label = conditionLabels?.[i];
        const labelX = (from.x + fromR + midX) / 2;
        const labelY = from.y - 8;
        return (
          <g key={i}
            onMouseEnter={() => setHoveredSpur(i)}
            onMouseLeave={() => setHoveredSpur(null)}
            style={{ cursor: 'pointer' }}
          >
            <line x1={from.x + fromR} y1={from.y} x2={midX} y2={from.y} {...lineStyle(active, spurDashed)} />
            {/* transparent hitbox — ends 2px before bus so bus area stays non-interactive */}
            <line x1={from.x + fromR} y1={from.y} x2={midX - 2} y2={from.y} stroke="transparent" strokeWidth={8} />
            {active && label && (
              <text x={labelX} y={labelY} textAnchor="middle" fontSize={10} fill="#ffffff"
                style={{ pointerEvents: 'none' }}>
                {label}
              </text>
            )}
          </g>
        );
      })}
      {/* section2: bus segments — each dashed only when both adjacent spurs did not run */}
      {busSegments(midX, busPts)}
      {/* section3: bus → dest — solid if dest ran */}
      <line
        x1={midX} y1={to.y} x2={to.x - toR} y2={to.y}
        markerEnd="url(#arrow)"
        {...lineStyle(trunkActive, trunkDashed)}
      />
    </g>
  );
};

export default FanEdgeGroup;
