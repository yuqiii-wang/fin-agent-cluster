/**
 * TaskDetail — shows a single task's details.
 *
 * Input and non-streaming output are surfaced via onViewData so the caller
 * renders them in the bottom DataViewer panel.
 *
 * For streaming tasks (task.is_streaming):
 *  - When live: stream is opened in the output panel automatically.
 *  - On completion: proactively fetches full output from backend (thinking as
 *    Markdown, answer as Json) and opens the hybrid view in the output panel.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Button, Descriptions, Space, Spin, Tag, Typography } from 'antd';
import { StopOutlined } from '@ant-design/icons';
import { viewTypeToMode } from '../DataViewer';
import { STATUS_TAG_COLOR } from '../../constants/statusColors';
import { isWorkActive } from '../../constants/lifecycleStatus';
import { getTask } from '../../api/threads';
import type { TaskInfo } from '../../types';
import type { DataViewerMode } from '../DataViewer/index';

const { Title, Text } = Typography;

interface Props {
  task: TaskInfo;
  threadId: string;
  /** Live token text forwarded from the thread-level centrifugo-llm subscription (unused — stream opens in output panel). */
  liveStream?: string;
  /** Called when the user wants to inspect data in the bottom DataViewer panel. */
  onViewData?: (label: string, data: unknown, opts?: { mode?: DataViewerMode; viewSchema?: Record<string, string>; fieldList?: boolean; taskId?: string }) => void;
  /** Called when the user cancels this task. */
  onCancelTask?: (taskId: string, nodeId?: string) => void;
  /** ID currently being cancelled (shows loading state). */
  cancellingId?: string | null;
}

const TaskDetail: React.FC<Props> = ({ task, threadId, onViewData, onCancelTask, cancellingId }) => {
  const [fetchingTask, setFetchingTask] = useState(false);
  const [localTask, setLocalTask] = useState<TaskInfo | null>(null);
  const [isHeaderHovered, setIsHeaderHovered] = useState(false);
  const fetchedTaskIdRef = useRef<string | null>(null);
  const openedStreamRef = useRef<string | null>(null);

  // Reset when navigating to a different task.
  useEffect(() => {
    setFetchingTask(false);
    setLocalTask(null);
    fetchedTaskIdRef.current = null;
    openedStreamRef.current = null;
  }, [task.task_id]);

  // Open stream in the output panel when the task goes live.
  useEffect(() => {
    if (!task.is_streaming || task.status !== 'running') return;
    if (openedStreamRef.current === task.task_id) return;
    openedStreamRef.current = task.task_id;
    onViewData?.(`${task.task_name} · Stream`, undefined, {
      mode: 'stream',
      taskId: task.task_id,
    });
  }, [task.is_streaming, task.status, task.task_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch full output from DB when the streaming task completes (driven by SSE status update).
  useEffect(() => {
    if (!task.is_streaming || task.status !== 'completed') return;
    if (fetchedTaskIdRef.current === task.task_id) return;
    fetchedTaskIdRef.current = task.task_id;
    setFetchingTask(true);
    getTask(threadId, task.task_id)
      .then((t) => {
        setLocalTask(t);
        onViewData?.(`${t.task_name} · Output`, t.output, {
          mode: viewTypeToMode(t.view_type),
          viewSchema: t.view_schema,
          fieldList: true,
        });
      })
      .catch(() => { /* backend fetch errors are non-critical; display will fallback */ })
      .finally(() => setFetchingTask(false));
  }, [task.is_streaming, task.status, task.task_id, threadId]); // eslint-disable-line react-hooks/exhaustive-deps

  const isLive = !!task.is_streaming && task.status === 'running';
  const streamCompleted = !!task.is_streaming && task.status === 'completed';

  // Resolved task for display: prefer freshly fetched localTask for completed streaming tasks.
  const displayTask = localTask ?? task;

  return (
    <div style={{ padding: '0 4px' }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}
        onMouseEnter={() => setIsHeaderHovered(true)}
        onMouseLeave={() => setIsHeaderHovered(false)}
      >
        <Title level={5} style={{ margin: 0 }}>{task.task_name}</Title>
        <Tag color={STATUS_TAG_COLOR[task.status] ?? 'default'}>{task.status}</Tag>
        {isWorkActive(task.status) && onCancelTask && isHeaderHovered && (
          <Button
            size="small"
            danger
            icon={<StopOutlined />}
            loading={cancellingId === task.task_id}
            onClick={() => onCancelTask(task.task_id, task.node_id)}
            style={{ marginLeft: 'auto' }}
          />
        )}
      </div>

      <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Task ID">
          <Text copyable code style={{ fontSize: 11 }}>{task.task_id}</Text>
        </Descriptions.Item>
      </Descriptions>

      <Space size="small" style={{ marginBottom: 12 }}>
        {task.input && (
          <Button
            size="small"
            onClick={() => onViewData?.(`${task.task_name} · Input`, task.input)}
          >
            View Input
          </Button>
        )}
        {/* For completed streaming tasks: "View Output" sends hybrid thinking+answer to the panel. */}
        {streamCompleted && localTask?.output && (
          <Button
            size="small"
            onClick={() => onViewData?.(`${task.task_name} · Output`, localTask.output, {
              mode: viewTypeToMode(localTask.view_type),
              viewSchema: localTask.view_schema,
              fieldList: true,
            })}
          >
            View Output
          </Button>
        )}
        {/* Non-streaming tasks: "View Output" sends raw output to the panel with proper mode. */}
        {!task.is_streaming && !!displayTask.output && (
          <Button
            size="small"
            onClick={() => onViewData?.(`${task.task_name} · Output`, displayTask.output, {
              mode: viewTypeToMode(displayTask.view_type),
            })}
          >
            View Output
          </Button>
        )}
      </Space>

      {/* After stream ends: spinner while fetching full output from DB. */}
      {streamCompleted && fetchingTask && (
        <Spin size="small" />
      )}
    </div>
  );
};

export default TaskDetail;
