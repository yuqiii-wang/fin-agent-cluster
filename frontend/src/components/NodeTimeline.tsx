/**
 * NodeTimeline — horizontal bar chart showing each node's elapsed time.
 * Ordered by start time.
 */

import React, { useMemo } from 'react';
import type { NodeInfo } from '../types';

const STATUS_COLORS: Record<string, string> = {
  pending:   '#595959',
  running:   '#1677ff',
  completed: '#52c41a',
  failed:    '#ff4d4f',
  cancelled: '#faad14',
};

interface Props {
  nodes: NodeInfo[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

const BAR_HEIGHT = 20;
const ROW_GAP = 10;
const LABEL_W = 140;
const CHART_W = 560;
const PADDING = 12;

const NodeTimeline: React.FC<Props> = ({ nodes, selectedNodeId, onSelectNode }) => {
  const visible = useMemo(
    () =>
      nodes
        .filter((n) => n.started_at && n.elapsed_ms > 0)
        .sort(
          (a, b) =>
            new Date(a.started_at!).getTime() - new Date(b.started_at!).getTime(),
        ),
    [nodes],
  );

  if (visible.length === 0) {
    return (
      <div style={{ color: '#595959', fontSize: 12, padding: '8px 0' }}>
        No elapsed data yet.
      </div>
    );
  }

  const t0 = Math.min(...visible.map((n) => new Date(n.started_at!).getTime()));
  const maxEnd = Math.max(
    ...visible.map((n) => new Date(n.started_at!).getTime() + n.elapsed_ms),
  );
  const totalSpan = maxEnd - t0 || 1;

  const svgH = visible.length * (BAR_HEIGHT + ROW_GAP) + PADDING * 2;
  const svgW = LABEL_W + CHART_W + PADDING * 2;

  return (
    <svg width="100%" viewBox={`0 0 ${svgW} ${svgH}`} style={{ fontFamily: 'sans-serif' }}>
      {visible.map((n, i) => {
        const startMs = new Date(n.started_at!).getTime() - t0;
        const x = LABEL_W + PADDING + (startMs / totalSpan) * CHART_W;
        const w = Math.max(2, (n.elapsed_ms / totalSpan) * CHART_W);
        const y = PADDING + i * (BAR_HEIGHT + ROW_GAP);
        const color = STATUS_COLORS[n.status] ?? '#8c8c8c';
        const isSelected = n.node_id === selectedNodeId;
        const label = n.node_name.replace(/_/g, ' ');
        const dur =
          n.elapsed_ms < 1000 ? `${n.elapsed_ms}ms` : `${(n.elapsed_ms / 1000).toFixed(1)}s`;

        return (
          <g
            key={n.node_id}
            style={{ cursor: 'pointer' }}
            onClick={() => onSelectNode(n.node_id)}
          >
            {/* Label */}
            <text
              x={LABEL_W + PADDING - 6}
              y={y + BAR_HEIGHT / 2 + 4}
              textAnchor="end"
              fontSize={11}
              fill={isSelected ? '#1677ff' : '#bfbfbf'}
            >
              {label}
            </text>
            {/* Bar */}
            <rect
              x={x}
              y={y}
              width={w}
              height={BAR_HEIGHT}
              rx={4}
              fill={color}
              fillOpacity={0.85}
              stroke={isSelected ? '#fff' : 'none'}
              strokeWidth={isSelected ? 1.5 : 0}
            />
            {/* Duration label inside or after bar */}
            {w > 40 ? (
              <text
                x={x + w / 2}
                y={y + BAR_HEIGHT / 2 + 4}
                textAnchor="middle"
                fontSize={10}
                fill="#fff"
                pointerEvents="none"
              >
                {dur}
              </text>
            ) : (
              <text
                x={x + w + 4}
                y={y + BAR_HEIGHT / 2 + 4}
                fontSize={10}
                fill="#bfbfbf"
                pointerEvents="none"
              >
                {dur}
              </text>
            )}
          </g>
        );
      })}

      {/* Time axis */}
      <line
        x1={LABEL_W + PADDING}
        y1={PADDING - 4}
        x2={LABEL_W + PADDING + CHART_W}
        y2={PADDING - 4}
        stroke="#303030"
        strokeWidth={1}
      />
    </svg>
  );
};

export default NodeTimeline;
