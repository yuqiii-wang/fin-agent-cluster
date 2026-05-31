/**
 * AgentMemoryPanel — read-only list of this node's completed-task memory.
 *
 * Each entry is one completed task for the node: its task_name, status and
 * description.  Clicking an entry opens the task's stored output in the data
 * viewer.  Memory is derived directly from finished task outputs — there are
 * no mutating operations (forget/compact) on it.
 */

import React from 'react';
import { Tag, Typography } from 'antd';
import { STATUS_TAG_COLOR } from '../../../constants/statusColors';
import {
  COLOR_BORDER_INACTIVE,
  COLOR_BRAND_BLUE_SUBTLE,
  COLOR_TEXT_SECONDARY,
} from '../../../constants/styleColors';
import type { TaskMemory } from '../../../types';

const { Text } = Typography;

/** Convert a task memory entry to a markdown string for the data viewer. */
function outputMarkdown(entry: TaskMemory): string {
  const header = `**${entry.task_name}** · ${entry.status}`;
  const desc = entry.description ? `\n\n${entry.description}` : '';
  const output = entry.output
    ? `\n\n\`\`\`json\n${JSON.stringify(entry.output, null, 2)}\n\`\`\``
    : '\n\n_No stored output._';
  return `${header}${desc}${output}`;
}

interface Props {
  memory: TaskMemory[];
  onViewData?: (label: string, data: string) => void;
}

const AgentMemoryPanel: React.FC<Props> = ({ memory, onViewData }) => {
  if (memory.length === 0) {
    return <Text type="secondary" style={{ fontSize: 12 }}>No completed tasks yet.</Text>;
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Text strong style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY }}>
          MEMORY ({memory.length})
        </Text>
      </div>

      {memory.map((entry) => (
        <div
          key={entry.task_id}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 8,
            padding: '5px 8px',
            marginBottom: 3,
            borderRadius: 4,
            borderLeft: `3px solid ${COLOR_BRAND_BLUE_SUBTLE || COLOR_BORDER_INACTIVE}`,
            cursor: onViewData ? 'pointer' : 'default',
          }}
          onClick={onViewData ? () => onViewData(`Memory · ${entry.task_name}`, outputMarkdown(entry)) : undefined}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <Text style={{ fontSize: 11, fontWeight: 600 }}>{entry.task_name}</Text>
              <Tag color={STATUS_TAG_COLOR[entry.status] ?? 'default'} style={{ fontSize: 10, margin: 0 }}>
                {entry.status}
              </Tag>
            </div>
            {entry.description && (
              <Text style={{ fontSize: 11, color: COLOR_TEXT_SECONDARY }}>
                {entry.description.slice(0, 140)}
              </Text>
            )}
          </div>
        </div>
      ))}
    </>
  );
};

export default AgentMemoryPanel;
