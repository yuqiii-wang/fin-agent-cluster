/**
 * TaskDetail — shows a single task's details.
 *
 * Input and non-streaming output are surfaced via onViewData so the caller
 * renders them in the bottom DataViewer panel.
 *
 * For streaming tasks (task.is_streaming):
 *  - While live: stream rendered inline.
 *  - On completion: thinking shown inline (collapsible); answer button → onViewData.
 */

import React, { useEffect, useState } from 'react';
import { Button, Descriptions, Space, Tag, Typography } from 'antd';
import { StopOutlined } from '@ant-design/icons';
import DataViewer from '../DataViewer';
import { STATUS_TAG_COLOR } from '../../constants/statusColors';
import { isWorkActive } from '../../constants/lifecycleStatus';
import type { TaskInfo } from '../../types';

const { Title, Text } = Typography;

interface Props {
  task: TaskInfo;
  threadId: string;
  /** Live token text forwarded from the thread-level centrifugo-llm subscription. */
  liveStream?: string;
  /** Called when the user wants to inspect data in the bottom DataViewer panel. */
  onViewData?: (label: string, data: unknown) => void;
  /** Called when the user cancels this task. */
  onCancelTask?: (taskId: string, nodeId?: string) => void;
  /** ID currently being cancelled (shows loading state). */
  cancellingId?: string | null;
}

const TaskDetail: React.FC<Props> = ({ task, threadId, liveStream, onViewData, onCancelTask, cancellingId }) => {
  const [streamingDone, setStreamingDone] = useState(false);
  const [isHeaderHovered, setIsHeaderHovered] = useState(false);

  // Reset when navigating to a different task.
  useEffect(() => {
    setStreamingDone(false);
  }, [task.task_id]);

  const isStreaming = !!task.is_streaming && !streamingDone;
  const isRunning = task.status === 'running';
  const isLive = isStreaming && isRunning;

  // For completed streaming tasks: answer goes to the DataViewer panel.
  const completedAnswer = !isLive && isStreaming
    ? (task.output?.answer as string | undefined)
    : undefined;

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
        {/* For completed streaming tasks: "View Output" sends answer text to the panel. */}
        {!isLive && isStreaming && completedAnswer && (
          <Button
            size="small"
            onClick={() => onViewData?.(`${task.task_name} · Output`, completedAnswer)}
          >
            View Output
          </Button>
        )}
        {/* Non-streaming tasks: "View Output" sends raw JSON to the panel. */}
        {!isStreaming && task.output && (
          <Button
            size="small"
            onClick={() => onViewData?.(`${task.task_name} · Output`, task.output)}
          >
            View Output
          </Button>
        )}
      </Space>

      {/* Streaming output: live stream inline; on completion, thinking stays inline. */}
      {isStreaming && (
        <DataViewer
          mode="stream"
          text={liveStream}
          isLive={isLive}
          task={task}
          threadId={threadId}
          onStreamEnd={() => setStreamingDone(true)}
          maxHeight={320}
        />
      )}
    </div>
  );
};

export default TaskDetail;
