import React from 'react';
import { STATUS_BRIGHT, STATUS_DARK } from '../../constants/statusColors';
import { COLOR_SURFACE_DEEP, COLOR_TEXT_BRIGHT, COLOR_TEXT_MUTED, COLOR_TEXT_TASK_DIM, COLOR_TEXT_TASK_HOV, COLOR_TICK_TASK, COLOR_STATUS_DARK_FALLBACK } from '../../constants/styleColors';
import { AXIS_TICKS, LABEL_W, NARROW_PCT, TASK_H } from './constants';
import { formatMs } from './utils';
import type { NodeInfo, TaskInfo } from '../../types';

const sdark   = (s: string) => STATUS_DARK[s]   ?? COLOR_STATUS_DARK_FALLBACK;
const sbright = (s: string) => STATUS_BRIGHT[s] ?? COLOR_TEXT_MUTED;

interface Props {
  node: NodeInfo;
  nodeTaskMap: Map<string, TaskInfo[]>;
  hoveredTaskId: string | null;
  setHoveredTaskId: (id: string | null) => void;
  pct: (ms: number) => number;
  tMin: number;
}

const TaskGantt: React.FC<Props> = ({ node, nodeTaskMap, hoveredTaskId, setHoveredTaskId, pct, tMin }) => {
  const nodeStartTs = node.started_at ? new Date(node.started_at).getTime() : tMin;

  return (
    <>
      {(nodeTaskMap.get(node.node_id) ?? []).map(task => {
        const isHov       = hoveredTaskId === task.task_id;
        const taskStart   = task.created_at ? new Date(task.created_at).getTime() : nodeStartTs;
        const taskEnd     = task.updated_at  ? new Date(task.updated_at).getTime()  : taskStart + 1;
        const taskElapsed = Math.max(taskEnd - taskStart, 1);
        const lPct        = pct(taskStart - tMin);
        const wPct        = pct(taskElapsed);
        const isNarrow    = wPct < NARROW_PCT;
        const elapsed     = formatMs(taskElapsed);

        return (
          <div
            key={task.task_id}
            style={{ display: 'flex', alignItems: 'center', marginBottom: 3 }}
            onMouseEnter={() => setHoveredTaskId(task.task_id)}
            onMouseLeave={() => setHoveredTaskId(null)}
          >
            <div
              style={{
                width: LABEL_W, flexShrink: 0, paddingRight: 8, textAlign: 'right',
                color: isHov ? COLOR_TEXT_TASK_HOV : COLOR_TEXT_TASK_DIM, fontSize: 11,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                transition: 'color 0.15s',
              }}
              title={task.task_name}
            >
              {isHov && isNarrow ? `└ ${task.task_name} · ${elapsed}` : `└ ${task.task_name}`}
            </div>

            <div style={{ flex: 1, position: 'relative', height: TASK_H, background: COLOR_SURFACE_DEEP, borderRadius: 2, overflow: 'hidden' }}>
              {AXIS_TICKS.slice(1, -1).map(f => (
                <div key={f} style={{ position: 'absolute', left: `${f * 100}%`, top: 0, bottom: 0, width: 1, background: COLOR_TICK_TASK }} />
              ))}
              <div
                style={{
                  position: 'absolute', left: `${lPct}%`, width: `${wPct}%`,
                  height: '100%', background: isHov ? sbright(task.status) : sdark(task.status),
                  borderRadius: 2, transition: 'background 0.15s',
                  display: 'flex', alignItems: 'center', paddingLeft: 4,
                  boxSizing: 'border-box', overflow: 'hidden',
                }}
              >
                {isHov && !isNarrow && (
                  <span style={{ color: COLOR_TEXT_BRIGHT, fontSize: 9, whiteSpace: 'nowrap' }}>{elapsed}</span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
};

export default TaskGantt;
