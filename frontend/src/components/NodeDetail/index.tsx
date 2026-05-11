/**
 * NodeDetail — shows a selected node's details with overlay navigation.
 *
 * Views (mutually exclusive, full-panel):
 *  - node (default): meta info + input/output action buttons + task list
 *  - task: TaskDetail overlay for the selected task
 *
 * Input / output data is surfaced via the onViewData callback so the
 * caller (ThreadView) can render it in the bottom data panel.
 */

import React, { useEffect, useState } from 'react';
import { Button, Descriptions, Space, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, StopOutlined } from '@ant-design/icons';
import TaskDetail from './TaskDetail';
import SubgraphNode from './SubgraphNode';
import { COLOR_SURFACE_RAISED, COLOR_TEXT_SECONDARY } from '../../constants/styleColors';
import { STATUS_HEX, STATUS_TAG_COLOR } from '../../constants/statusColors';
import { isWorkActive } from '../../constants/lifecycleStatus';
import type { NodeInfo, TaskInfo } from '../../types';

const { Title, Text } = Typography;

interface Props {
  node: NodeInfo;
  nodes?: NodeInfo[];
  tasks: TaskInfo[];
  threadId: string;
  tokenStreams?: Record<string, string>;
  /** Called when the user wants to inspect data in the bottom DataViewer panel. */
  onViewData?: (label: string, data: unknown) => void;
  /** Called when the user clicks a child node (subgraph navigation). */
  onSelectNode?: (nodeId: string) => void;
  /** Called when the user cancels the node. */
  onCancelNode?: (nodeId: string) => void;
  /** Called when the user cancels a task. */
  onCancelTask?: (taskId: string, nodeId?: string) => void;
  /** ID currently being cancelled (shows loading state). */
  cancellingId?: string | null;
}

type View = { type: 'node' } | { type: 'task'; taskId: string };

const NodeDetail: React.FC<Props> = ({ node, nodes = [], tasks, threadId, tokenStreams = {}, onViewData, onSelectNode, onCancelNode, onCancelTask, cancellingId }) => {
  const [view, setView] = useState<View>({ type: 'node' });
  const [isHeaderHovered, setIsHeaderHovered] = useState(false);
  const [hoveredTaskId, setHoveredTaskId] = useState<string | null>(null);

  const nodeTasks = tasks.filter(
    (t) => t.node_id === node.node_id || t.node_name === node.node_name,
  );

  // Reset to default view whenever the displayed node changes.
  useEffect(() => {
    setView({ type: 'node' });
  }, [node.node_id]);

  const backBtn = (
    <Button
      size="small"
      type="text"
      icon={<ArrowLeftOutlined />}
      onClick={() => setView({ type: 'node' })}
      style={{ marginBottom: 12, padding: '0 4px', color: COLOR_TEXT_SECONDARY }}
    >
      Back
    </Button>
  );

  // ── Task overlay ──────────────────────────────────────────────────────────
  if (view.type === 'task') {
    const task = nodeTasks.find((t) => t.task_id === view.taskId);
    return (
      <div>
        {backBtn}
        {task ? (
          <TaskDetail
            key={task.task_id}
            task={task}
            threadId={threadId}
            liveStream={tokenStreams[task.task_id]}
            onViewData={onViewData}
            onCancelTask={onCancelTask}
            cancellingId={cancellingId}
          />
        ) : (
          <Text type="secondary">Task not found.</Text>
        )}
      </div>
    );
  }

  // ── Default node view ─────────────────────────────────────────────────────
  return (
    <div>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}
        onMouseEnter={() => setIsHeaderHovered(true)}
        onMouseLeave={() => setIsHeaderHovered(false)}
      >
        <Title level={5} style={{ margin: 0 }}>{node.node_name}</Title>
        <Tag color={STATUS_TAG_COLOR[node.status] ?? 'default'}>{node.status}</Tag>
        {node.type !== 'Typical' && <Tag>{node.type}</Tag>}
        {isWorkActive(node.status) && onCancelNode && isHeaderHovered && (
          <Button
            size="small"
            danger
            icon={<StopOutlined />}
            loading={cancellingId === node.node_id}
            onClick={() => onCancelNode(node.node_id)}
            style={{ marginLeft: 'auto' }}
          />
        )}
      </div>

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Node ID">
          <Text copyable code style={{ fontSize: 11 }}>{node.node_id}</Text>
        </Descriptions.Item>
      </Descriptions>

      {(node.input || node.output) && (
        <Space size="small" style={{ marginBottom: 12 }}>
          {node.input && (
            <Button
              size="small"
              onClick={() => onViewData?.(`${node.node_name} · Input`, node.input)}
            >
              Input
            </Button>
          )}
          {node.output && (
            <Button
              size="small"
              onClick={() => onViewData?.(`${node.node_name} · Output`, node.output)}
            >
              Output
            </Button>
          )}
        </Space>
      )}

      {nodeTasks.length > 0 && (
        <>
          <Text strong style={{ fontSize: 12, color: COLOR_TEXT_SECONDARY, display: 'block', marginBottom: 6 }}>
            TASKS ({nodeTasks.length})
          </Text>
          {nodeTasks.map((t) => (
            <div
              key={t.task_id}
              style={{
                cursor: 'pointer',
                borderRadius: 4,
                padding: '6px 10px',
                marginBottom: 3,
                borderLeft: `3px solid ${STATUS_HEX[t.status] ?? '#8c8c8c'}`,
                background: hoveredTaskId === t.task_id ? COLOR_SURFACE_RAISED : 'transparent',
                transition: 'background 0.15s',
              }}
              onClick={() => setView({ type: 'task', taskId: t.task_id })}
              onMouseEnter={() => setHoveredTaskId(t.task_id)}
              onMouseLeave={() => setHoveredTaskId(null)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Text style={{ flex: 1, fontSize: 12 }}>{t.task_name}</Text>
                <Tag color={STATUS_TAG_COLOR[t.status] ?? 'default'} style={{ fontSize: 10 }}>
                  {t.status}
                </Tag>
                {hoveredTaskId === t.task_id && isWorkActive(t.status) && onCancelTask && (
                  <Button
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    loading={cancellingId === t.task_id}
                    onClick={(e) => { e.stopPropagation(); onCancelTask(t.task_id, t.node_id); }}
                  />
                )}
              </div>
            </div>
          ))}
        </>
      )}

      {node.type === 'Subgraph' && onSelectNode && (
        <div style={{ marginTop: nodeTasks.length > 0 ? 12 : 0 }}>
          <SubgraphNode
            childNodes={nodes.filter(n => n.parent_node_id === node.node_id)}
            onSelectNode={onSelectNode}
          />
        </div>
      )}
    </div>
  );
};

export default NodeDetail;
