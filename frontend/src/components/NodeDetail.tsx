/**
 * NodeDetail — shows a selected node's input/output and its task list.
 * Clicking a task expands the TaskDetail panel.
 */

import React, { useState } from 'react';
import { Collapse, Descriptions, Tag, Typography } from 'antd';
import type { CollapseProps } from 'antd';
import TaskDetail from './TaskDetail';
import type { NodeInfo, TaskInfo } from '../types';

const { Title, Text } = Typography;

const STATUS_COLOR: Record<string, string> = {
  pending:   'default',
  running:   'processing',
  completed: 'success',
  failed:    'error',
  cancelled: 'warning',
  wrong:     'error',
};

interface Props {
  node: NodeInfo;
  tasks: TaskInfo[];
  threadId: string;
  tokenStreams?: Record<string, string>;
}

const NodeDetail: React.FC<Props> = ({ node, tasks, threadId, tokenStreams = {} }) => {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const nodeTasks = tasks.filter((t) => t.node_id === node.node_id || t.node_name === node.node_name);
  const selectedTask = nodeTasks.find((t) => t.task_id === selectedTaskId) ?? null;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Title level={5} style={{ margin: 0 }}>{node.node_name}</Title>
        <Tag color={STATUS_COLOR[node.status] ?? 'default'}>{node.status}</Tag>
        <Tag>{node.type}</Tag>
      </div>

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Node ID">
          <Text copyable code style={{ fontSize: 11 }}>{node.node_id}</Text>
        </Descriptions.Item>
        {node.started_at && (
          <Descriptions.Item label="Started">
            {new Date(node.started_at).toLocaleTimeString()}
          </Descriptions.Item>
        )}
        {node.elapsed_ms > 0 && (
          <Descriptions.Item label="Elapsed">
            {node.elapsed_ms < 1000 ? `${node.elapsed_ms} ms` : `${(node.elapsed_ms / 1000).toFixed(2)} s`}
          </Descriptions.Item>
        )}
      </Descriptions>

      {node.input && (
        <Collapse
          ghost
          size="small"
          style={{ marginBottom: 8 }}
          items={[
            {
              key: 'input',
              label: <Text strong style={{ fontSize: 12 }}>Input</Text>,
              children: (
                <pre
                  style={{
                    background: '#141414',
                    borderRadius: 6,
                    padding: '8px 12px',
                    border: '1px solid #303030',
                    fontSize: 11,
                    margin: 0,
                    maxHeight: 160,
                    overflowY: 'auto',
                    color: '#d9d9d9',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {JSON.stringify(node.input, null, 2)}
                </pre>
              ),
            },
          ] satisfies CollapseProps['items']}
        />
      )}

      {node.output && (
        <Collapse
          ghost
          size="small"
          style={{ marginBottom: 8 }}
          items={[
            {
              key: 'output',
              label: <Text strong style={{ fontSize: 12 }}>Output</Text>,
              children: (
                <pre
                  style={{
                    background: '#141414',
                    borderRadius: 6,
                    padding: '8px 12px',
                    border: '1px solid #303030',
                    fontSize: 11,
                    margin: 0,
                    maxHeight: 160,
                    overflowY: 'auto',
                    color: '#d9d9d9',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {JSON.stringify(node.output, null, 2)}
                </pre>
              ),
            },
          ] satisfies CollapseProps['items']}
        />
      )}

      {nodeTasks.length > 0 && (
        <>
          <Text strong style={{ fontSize: 12, color: '#8c8c8c', display: 'block', marginBottom: 6 }}>
            TASKS ({nodeTasks.length})
          </Text>
          <div>
            {nodeTasks.map((t) => (
              <div
                key={t.task_id}
                style={{
                  cursor: 'pointer',
                  borderRadius: 4,
                  padding: '4px 8px',
                  background: t.task_id === selectedTaskId ? 'rgba(22,119,255,0.12)' : 'transparent',
                }}
                onClick={() => setSelectedTaskId(t.task_id === selectedTaskId ? null : t.task_id)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
                  <Text style={{ flex: 1, fontSize: 12 }}>{t.task_name}</Text>
                  <Tag color={STATUS_COLOR[t.status] ?? 'default'} style={{ fontSize: 10 }}>
                    {t.status}
                  </Tag>
                </div>
              </div>
            ))}
          </div>
          {selectedTask && (
            <div
              style={{
                marginTop: 12,
                borderTop: '1px solid #303030',
                paddingTop: 12,
              }}
            >
              <TaskDetail task={selectedTask} threadId={threadId} liveStream={tokenStreams[selectedTask.task_id]} />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default NodeDetail;
