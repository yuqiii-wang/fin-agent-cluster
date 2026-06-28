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
import { Button, Descriptions, Space, Tag, Tooltip, Typography, message } from 'antd';
import { ArrowLeftOutlined, BranchesOutlined, ClearOutlined, StopOutlined } from '@ant-design/icons';
import { viewTypeToMode } from '../DataViewer/index';
import TaskDetail from './TaskDetail';
import SubgraphNode from './SubgraphNode';
import { COLOR_SURFACE_RAISED, COLOR_TEXT_SECONDARY } from '../../constants/styleColors';
import { STATUS_HEX, STATUS_TAG_COLOR } from '../../constants/statusColors';
import { isWorkActive, TERMINAL_WORK_STATUSES } from '../../constants/lifecycleStatus';
import { invalidateNodeCache } from '../../api/threads';

import type { NodeInfo, TaskInfo, TaskRunEntry } from '../../types';
import type { DataViewerMode } from '../DataViewer/index';

const { Title, Text } = Typography;

interface Props {
  node: NodeInfo;
  nodes?: NodeInfo[];
  tasks: TaskInfo[];
  threadId: string;
  tokenStreams?: Record<string, string>;
  /** Accumulated SSE-driven task run log for running output display. */
  taskRunLog?: TaskRunEntry[];
  /** True when the thread is still running (re-explore btn will be disabled). */
  threadActive?: boolean;
  /** Active version being viewed; used to mark shared nodes from older versions. */
  activeVersion?: number;
  /** Called when the user wants to inspect data in the bottom DataViewer panel. */
  onViewData?: (label: string, data: unknown, opts?: { mode?: DataViewerMode; viewSchema?: Record<string, string>; fieldList?: boolean; nodeContext?: 'input' | 'output'; nodeId?: string; taskId?: string; activeStatsView?: string }) => void;
  /** Called when the user clicks a child node (subgraph navigation). */
  onSelectNode?: (nodeId: string) => void;
  /** Called when the user cancels the node. */
  onCancelNode?: (nodeId: string) => void;
  /** Called when the user cancels a task. */
  onCancelTask?: (taskId: string, nodeId?: string) => void;
  /** ID currently being cancelled (shows loading state). */
  cancellingId?: string | null;
  /** Called when the user clicks Re-explore on a terminal node. */
  onReExplore?: (node: NodeInfo) => void;
}

type View = { type: 'node' } | { type: 'task'; taskId: string };

const NodeDetail: React.FC<Props> = ({ node, nodes = [], tasks, threadId, tokenStreams = {}, taskRunLog = [], threadActive = false, activeVersion, onViewData, onSelectNode, onCancelNode, onCancelTask, cancellingId, onReExplore }) => {
  const [view, setView] = useState<View>({ type: 'node' });
  const [isHeaderHovered, setIsHeaderHovered] = useState(false);
  const [hoveredTaskId, setHoveredTaskId] = useState<string | null>(null);
  const [invalidatingCache, setInvalidatingCache] = useState(false);

  const nodeTasks = tasks.filter(
    (t) => t.node_id === node.node_id,
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
            nodeStatus={node.status}
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
  const nodeVersion = node.version ?? 0;
  // A node is "shared" when it ran in an earlier version than the one currently viewed.
  const isShared = activeVersion !== undefined && nodeVersion < activeVersion;
  // Inner subgraph nodes (parent_node_id set) cannot be re-explored individually.
  const isInnerNode = !!node.parent_node_id;
  const isConditional = !!node.conditional_group;
  // Re-explore is available for: terminal nodes (any), active/running nodes (disabled), or conditional not-yet-run (topology-only) nodes.
  const canReExplore = !isInnerNode && !!onReExplore && (
    TERMINAL_WORK_STATUSES.has(node.status as never) ||
    isWorkActive(node.status) ||
    (isConditional && !!node.is_topology_only)
  );
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
        <Tooltip title={isShared ? `shared from v${nodeVersion}` : undefined}>
          <Tag color={isShared ? 'default' : nodeVersion > 0 ? 'blue' : undefined}
               style={{ cursor: isShared ? 'help' : 'default' }}>
            v{nodeVersion}{isShared ? ' (shared)' : ''}
          </Tag>
        </Tooltip>
        {isWorkActive(node.status) && !isConditional && onCancelNode && isHeaderHovered && (
          <Button
            size="small"
            danger
            icon={<StopOutlined />}
            loading={cancellingId === node.node_id}
            onClick={() => onCancelNode(node.node_id)}
            style={{ marginLeft: 'auto' }}
          />
        )}
        {canReExplore && (
          <Tooltip
            title={
              isWorkActive(node.status) && threadActive
                ? 'Node must finish before re-exploring'
                : node.is_topology_only
                ? 'Fork graph to run this conditional branch'
                : 'Fork graph from this node with different inputs'
            }
          >
            <Button
              size="small"
              icon={<BranchesOutlined />}
              disabled={isWorkActive(node.status) && threadActive}
              onClick={() => !(isWorkActive(node.status) && threadActive) && onReExplore!(node)}
              style={{ marginLeft: 'auto' }}
            >
              Re-explore
            </Button>
          </Tooltip>
        )}
        {node.status === 'completed' && nodeTasks.length > 0 && (
          <Tooltip title="Zero out task cache TTLs so tasks re-run on the next execution">
            <Button
              size="small"
              icon={<ClearOutlined />}
              loading={invalidatingCache}
              onClick={async () => {
                setInvalidatingCache(true);
                try {
                  const { invalidated } = await invalidateNodeCache(threadId, node.node_id);
                  message.success(`Cache invalidated for ${invalidated} task(s)`);
                } catch {
                  message.error('Failed to invalidate cache');
                } finally {
                  setInvalidatingCache(false);
                }
              }}
            >
              Invalidate Cache
            </Button>
          </Tooltip>
        )}
      </div>

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Node ID">
          <Text copyable code style={{ fontSize: 11 }}>{node.node_id}</Text>
        </Descriptions.Item>
      </Descriptions>

      {(node.input || node.output || !node.is_topology_only) && (
        <Space size="small" style={{ marginBottom: 12 }}>
          {node.input && (
            <Button
              size="small"
              onClick={() => onViewData?.(`${node.node_name} · Input`, node.input, { nodeContext: 'input' })}
            >
              Input
            </Button>
          )}
          {(node.output || taskRunLog.length > 0) && (
            <Button
              size="small"
              onClick={() => onViewData?.(`${node.node_name} · Output`, node.output, {
                mode: node.output ? viewTypeToMode(node.view_type) : undefined,
                viewSchema: node.view_schema as Record<string, string> | undefined,
                fieldList: !!node.output,
                nodeContext: 'output',
              })}
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
          {nodeTasks.map((t) => {
            // Only the status tag label/colour is adjusted: a paused task whose
            // node has since completed is labelled "completed" (green).  All
            // other affordances (border, timeline, cancel button) continue to
            // use the real status so they stay in the "paused" / orange state.
            const tagStatus = t.status === 'paused' && node.status === 'completed' ? 'completed' : t.status;
            return (
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
              onClick={() => {
                setView({ type: 'task', taskId: t.task_id });
                if (t.output) {
                  onViewData?.(`${t.task_name} · Output`, t.output, {
                    mode: viewTypeToMode(t.view_type),
                  });
                }
              }}
              onMouseEnter={() => setHoveredTaskId(t.task_id)}
              onMouseLeave={() => setHoveredTaskId(null)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Text style={{ flex: 1, fontSize: 12 }}>{t.task_name}</Text>
                <Tag color={STATUS_TAG_COLOR[tagStatus] ?? 'default'} style={{ fontSize: 10 }}>
                  {tagStatus}
                </Tag>
                {hoveredTaskId === t.task_id && isWorkActive(t.status) && onCancelTask && (
                  <Button
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    loading={cancellingId === t.task_id}
                    onClick={(e) => { e.stopPropagation(); onCancelTask(t.task_id, t.node_id); }}
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          );
          })}
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
