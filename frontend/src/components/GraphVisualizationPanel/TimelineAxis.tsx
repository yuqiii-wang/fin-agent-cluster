import type { GraphNode } from "./types";
import { statusColor } from "./layout";

function niceTickIntervalMs(totalMs: number): number {
  const raw = totalMs / 5;
  const exp = Math.floor(Math.log10(Math.max(raw, 1)));
  const mag = Math.pow(10, exp);
  const n = raw / mag;
  if (n < 1.5) return mag;
  if (n < 3.5) return 2 * mag;
  if (n < 7.5) return 5 * mag;
  return 10 * mag;
}

function fmtAxisTime(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export interface TimelineAxisProps {
  nodes: GraphNode[];
  hoveredNodeId: number;
  svgW: number;
}

export function TimelineAxis({ nodes, hoveredNodeId, svgW }: TimelineAxisProps) {
  const AXIS_H = 74;
  const BAR_H = 14;
  const BAR_H_HOVERED = 20;
  const BAR_Y = 8;
  const AXIS_Y = 40;
  const LABEL_Y = 56;
  const PAD = 40;

  const t0 = Math.min(...nodes.filter((n) => n.started_at_ms > 0).map((n) => n.started_at_ms));
  if (!isFinite(t0)) return null;
  const now = Date.now();
  const tMax = Math.max(...nodes.filter((n) => n.started_at_ms > 0).map((n) => n.ended_at_ms ?? now));
  const totalDuration = Math.max(tMax - t0, 1);
  const usableW = Math.max(svgW - 2 * PAD, 1);

  function toX(ms: number): number {
    return PAD + ((ms - t0) / totalDuration) * usableW;
  }

  const tickInterval = niceTickIntervalMs(totalDuration);
  const ticks: number[] = [];
  for (let t = 0; t <= totalDuration + tickInterval * 0.01; t += tickInterval) {
    ticks.push(t);
  }

  return (
    <svg width={svgW} height={AXIS_H} style={{ display: "block", marginTop: 2 }}>
      {nodes.filter((n) => n.started_at_ms > 0).map((node) => {
        const isHovered = node.node_execution_id === hoveredNodeId;
        const x1 = toX(node.started_at_ms);
        const x2 = toX(node.ended_at_ms ?? now);
        const w = Math.max(x2 - x1, 4);
        const barH = isHovered ? BAR_H_HOVERED : BAR_H;
        const barY = isHovered ? BAR_Y - 3 : BAR_Y;
        const color = isHovered ? statusColor(node.status) : "#595959";
        const opacity = isHovered ? 0.9 : 0.3;
        const elapsedMs = (node.ended_at_ms ?? now) - node.started_at_ms;
        return (
          <g key={node.node_execution_id}>
            <rect
              x={x1}
              y={barY}
              width={w}
              height={barH}
              fill={color}
              opacity={opacity}
              rx={3}
            />
            {isHovered && (
              <text
                x={x1 + w / 2}
                y={barY + barH + 10}
                textAnchor="middle"
                fontSize={10}
                fill={statusColor(node.status)}
                fontWeight={600}
              >
                {fmtAxisTime(elapsedMs)}
              </text>
            )}
          </g>
        );
      })}
      <line x1={PAD} y1={AXIS_Y} x2={svgW - PAD} y2={AXIS_Y} stroke="#595959" strokeWidth={1} opacity={0.4} />
      {ticks.map((t) => {
        const x = PAD + (t / totalDuration) * usableW;
        return (
          <g key={t}>
            <line x1={x} y1={AXIS_Y} x2={x} y2={AXIS_Y + 5} stroke="#595959" strokeWidth={1} opacity={0.4} />
            <text x={x} y={LABEL_Y} textAnchor="middle" fontSize={10} fill="#8c8c8c">
              {fmtAxisTime(t)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
