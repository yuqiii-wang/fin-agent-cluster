/**
 * TaskDetail — shows a single task's input, output, and streaming viewer.
 */

import React from 'react';
import { Badge, Descriptions, Tag, Typography } from 'antd';
import StreamViewer from './StreamViewer';
import type { TaskInfo } from '../types';

const { Title, Text } = Typography;

const STATUS_COLOR: Record<string, string> = {
  pending:   'default',
  running:   'processing',
  completed: 'success',
  failed:    'error',
  cancelled: 'warning',
};

interface Props {
  task: TaskInfo;
  threadId: string;
  /** Live token text from the thread-level centrifugo-llm subscription. */
  liveStream?: string;
}

const TaskDetail: React.FC<Props> = ({ task, threadId, liveStream }) => {
  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Title level={5} style={{ margin: 0 }}>{task.task_name}</Title>
        <Tag color={STATUS_COLOR[task.status] ?? 'default'}>{task.status}</Tag>
      </div>

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Task ID">
          <Text copyable code style={{ fontSize: 11 }}>{task.task_id}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="Node">{task.node_name}</Descriptions.Item>
        {task.created_at && (
          <Descriptions.Item label="Started">
            {new Date(task.created_at).toLocaleTimeString()}
          </Descriptions.Item>
        )}
        {task.updated_at && (
          <Descriptions.Item label="Updated">
            {new Date(task.updated_at).toLocaleTimeString()}
          </Descriptions.Item>
        )}
      </Descriptions>

      {task.input && (
        <>
          <Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>INPUT</Text>
          <pre
            style={{
              background: '#141414',
              borderRadius: 6,
              padding: '8px 12px',
              border: '1px solid #303030',
              fontSize: 11,
              margin: '4px 0 12px',
              maxHeight: 160,
              overflowY: 'auto',
              color: '#d9d9d9',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {JSON.stringify(task.input, null, 2)}
          </pre>
        </>
      )}

      <Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>OUTPUT</Text>
      <div style={{ marginTop: 4 }}>
        <StreamViewer task={task} threadId={threadId} liveStream={liveStream} />
      </div>
    </div>
  );
};

export default TaskDetail;
