/**
 * TaskGantt — Gantt chart for all tasks in a thread.
 *
 * Each row represents one task, bars are placed on a shared time axis
 * anchored to the earliest created_at.
 */

import React, { useMemo } from 'react';
import type { TaskInfo } from '../types';

const STATUS_COLORS: Record<string, string> = {
  pending:   '#595959',
  running:   '#1677ff',
  completed: '#52c41a',
  failed:    '#ff4d4f',
  cancelled: '#faad14',
};

interface Props {
  tasks: TaskInfo[];
}

const BAR_HEIGHT = 18;
const ROW_GAP = 10;
const LABEL_W = 160;
const CHART_W = 520;
const PADDING = 12;

const TaskGantt: React.FC<Props> = ({ tasks }) => {
  const visible = useMemo(
    () =>
      tasks
        .filter((t) => t.created_at)
        .sort(
          (a, b) =>
            new Date(a.created_at!).getTime() - new Date(b.created_at!).getTime(),
        ),
    [tasks],
  );

  if (visible.length === 0) {
    return (
      <div style={{ color: '#595959', fontSize: 12, padding: '8px 0' }}>
        No task data yet.
      </div>
    );
  }

  const t0 = Math.min(...visible.map((t) => new Date(t.created_at!).getTime()));
  const now = Date.now();
  const ends = visible.map((t) => {
    const start = new Date(t.created_at!).getTime();
    const end = t.updated_at ? new Date(t.updated_at).getTime() : now;
    return end > start ? end : start + 1;
  });
  const maxEnd = Math.max(...ends);
  const totalSpan = maxEnd - t0 || 1;

  const svgH = visible.length * (BAR_HEIGHT + ROW_GAP) + PADDING * 2;
  const svgW = LABEL_W + CHART_W + PADDING * 2;

  return (
    <svg width="100%" viewBox={`0 0 ${svgW} ${svgH}`} style={{ fontFamily: 'sans-serif' }}>
      {visible.map((t, i) => {
        const start = new Date(t.created_at!).getTime() - t0;
        const end = (t.updated_at ? new Date(t.updated_at).getTime() : now) - t0;
        const x = LABEL_W + PADDING + (start / totalSpan) * CHART_W;
        const w = Math.max(2, ((end - start) / totalSpan) * CHART_W);
        const y = PADDING + i * (BAR_HEIGHT + ROW_GAP);
        const color = STATUS_COLORS[t.status] ?? '#8c8c8c';
        const durMs = end - start;
        const dur = durMs < 1000 ? `${durMs}ms` : `${(durMs / 1000).toFixed(1)}s`;
        const label = `${t.task_name} (${t.node_name})`;

        return (
          <g key={t.task_id}>
            {/* Label */}
            <text
              x={LABEL_W + PADDING - 6}
              y={y + BAR_HEIGHT / 2 + 4}
              textAnchor="end"
              fontSize={10}
              fill="#bfbfbf"
            >
              {label}
            </text>
            {/* Bar */}
            <rect x={x} y={y} width={w} height={BAR_HEIGHT} rx={3} fill={color} fillOpacity={0.85} />
            {/* Duration */}
            {w > 36 ? (
              <text
                x={x + w / 2}
                y={y + BAR_HEIGHT / 2 + 4}
                textAnchor="middle"
                fontSize={9}
                fill="#fff"
                pointerEvents="none"
              >
                {dur}
              </text>
            ) : (
              <text
                x={x + w + 4}
                y={y + BAR_HEIGHT / 2 + 4}
                fontSize={9}
                fill="#bfbfbf"
                pointerEvents="none"
              >
                {dur}
              </text>
            )}
          </g>
        );
      })}

      {/* Axis line */}
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

export default TaskGantt;
