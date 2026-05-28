import React, { useEffect, useState } from 'react';
import { Button, Card, Typography } from 'antd';
import { CaretRightOutlined, PauseOutlined, RetweetOutlined } from '@ant-design/icons';
import DataViewer, { viewTypeToMode } from '../DataViewer/index';
import { StatsViewSelect } from '../DataViewer/StatsViewer';
import AgentNodeRunningOutput from '../NodeDetail/Agent/AgentNodeRunningOutput';
import { retryFreshTask, continueTask, pauseTask } from '../../api/threads';
import type { TaskInfo, NodeInfo, TaskRunEntry } from '../../types';
import type { DetailData } from './types';

const { Text } = Typography;

const RETRYABLE_STATUSES = new Set(['completed', 'failed', 'cancelled', 'paused']);

interface Props {
  detailData: DetailData;
  onClose: () => void;
  tasks: TaskInfo[];
  nodes: NodeInfo[];
  threadId: string;
  taskRunLog?: TaskRunEntry[];
  tokenStreams?: Record<string, string>;
  /** Called immediately when a retry is initiated so the parent can re-establish SSE. */
  onRetry?: (taskId: string) => void;
}

const DetailDataPanel: React.FC<Props> = ({
  detailData,
  onClose,
  tasks,
  nodes,
  threadId,
  taskRunLog = [],
  tokenStreams = {},
  onRetry,
}) => {
  const [retrying, setRetrying] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [hovered, setHovered] = useState(false);

  const streamTask = detailData.taskId ? tasks.find(t => t.task_id === detailData.taskId) : undefined;
  const streamNode = streamTask?.node_id ? nodes.find(n => n.node_id === streamTask.node_id) : undefined;
  const isRetryableStream = !!(streamTask?.is_streaming &&
    streamNode?.status !== 'completed' &&
    (RETRYABLE_STATUSES.has(streamTask.status) || streamTask.status === 'running'));

  const handleRetry = async () => {
    if (!streamTask) return;
    onRetry?.(streamTask.task_id);
    setRetrying(true);
    try {
      await retryFreshTask(threadId, streamTask.task_id);
    } finally {
      setRetrying(false);
    }
  };

  const handleContinue = async () => {
    if (!streamTask) return;
    onRetry?.(streamTask.task_id);
    setContinuing(true);
    try {
      await continueTask(threadId, streamTask.task_id);
    } finally {
      setContinuing(false);
    }
  };

  const handlePause = async () => {
    if (!streamTask) return;
    setPausing(true);
    try {
      await pauseTask(threadId, streamTask.task_id);
    } finally {
      setPausing(false);
    }
  };

  const statsViews = (() => {
    const d = detailData.data as Record<string, unknown> | undefined;
    if (Array.isArray(d?.stats_views)) return d!.stats_views as string[];
    if (detailData.mode === 'mirror') {
      const taskId = d?.task_id as string | undefined;
      const resolved = taskId ? tasks.find(t => t.task_id === taskId) : undefined;
      const td = resolved?.output as Record<string, unknown> | undefined;
      if (Array.isArray(td?.stats_views)) return td!.stats_views as string[];
    }
    return [] as string[];
  })();

  const [activeStatsView, setActiveStatsView] = useState<string>(detailData.activeStatsView ?? statsViews[0] ?? '');
  useEffect(() => {
    setActiveStatsView(detailData.activeStatsView ?? statsViews[0] ?? '');
  }, [detailData.label]); // eslint-disable-line react-hooks/exhaustive-deps

  const resolvedMode = detailData.mode ??
    (typeof detailData.data === 'string'
      ? 'markdown'
      : (detailData.data as Record<string, unknown> | null)?.df_split
      ? 'dataframe'
      : 'json');

  // When a streaming task completes while DetailDataPanel is open (e.g. when
  // TaskDetail is not mounted and cannot call onViewData to switch modes),
  // automatically transition from stream mode to the completed output view.
  // The backend marks completed streaming tasks as view_type="Hybrid" with
  // view_schema {thinking: "Markdown", answer: "Json"}.
  const isCompletedStream =
    resolvedMode === 'stream' &&
    !!(streamTask?.status === 'completed' && streamTask?.is_streaming && streamTask?.output);
  const effectiveMode = isCompletedStream ? viewTypeToMode(streamTask!.view_type) : resolvedMode;
  const effectiveData = isCompletedStream
    ? streamTask!.output
    : (typeof detailData.data !== 'string' ? detailData.data : undefined);
  const effectiveText = isCompletedStream
    ? undefined
    : (typeof detailData.data === 'string'
      ? detailData.data
      : (resolvedMode === 'markdown' && typeof (detailData.data as Record<string, unknown> | null)?.markdown === 'string'
        ? (detailData.data as Record<string, unknown>).markdown as string
        : undefined));
  const effectiveViewSchema = isCompletedStream
    ? (streamTask!.view_schema as Record<string, string> | undefined)
    : detailData.viewSchema;
  const effectiveFieldList = isCompletedStream ? true : detailData.fieldList;
  const nodeTaskRunLog = detailData.nodeId
    ? taskRunLog.filter((entry) => entry.node_id === detailData.nodeId)
    : [];
  const showAgentRunningOutput =
    detailData.nodeContext === 'output' && nodeTaskRunLog.length > 0;
  // Always render DataViewer for stream mode (data=undefined is normal; task sub-handles tokens).
  const showDataViewer =
    effectiveMode === 'stream' ||
    effectiveData !== undefined ||
    effectiveText !== undefined;

  return (
    <Card
      size="small"
      title={<Text strong style={{ fontSize: 12 }}>{detailData.label}</Text>}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      extra={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {statsViews.length > 0 && (
            <StatsViewSelect
              statsViews={statsViews}
              activeView={activeStatsView || statsViews[0]}
              onChange={setActiveStatsView}
            />
          )}
          {isRetryableStream && hovered && (
            streamTask?.status === 'running' ? (
              <>
                <Button
                  size="small"
                  icon={<PauseOutlined />}
                  loading={pausing}
                  onClick={handlePause}
                  title="Pause task"
                  style={{ color: '#fa8c16', borderColor: '#fa8c16' }}
                >
                  Pause
                </Button>
                <Button
                  size="small"
                  icon={<RetweetOutlined />}
                  loading={retrying}
                  disabled={pausing}
                  onClick={handleRetry}
                  title="Pause then restart from scratch"
                >
                  Retry
                </Button>
              </>
            ) : streamTask?.status === 'paused' ? (
              <Button
                size="small"
                icon={<CaretRightOutlined />}
                loading={continuing}
                onClick={handleContinue}
                title="Resume from pause"
              >
                Resume
              </Button>
            ) : (
              <Button
                size="small"
                icon={<RetweetOutlined />}
                loading={retrying}
                onClick={handleRetry}
                title="Restart from scratch"
              >
                Retry
              </Button>
            )
          )}
          <Button size="small" type="text" onClick={onClose}>✕</Button>
        </div>
      }
      style={{ borderRadius: 8 }}
    >
      {showAgentRunningOutput && (
        <AgentNodeRunningOutput
          entries={nodeTaskRunLog}
          tokenStreams={tokenStreams}
          showTitle={false}
        />
      )}
      {showDataViewer && (
        <DataViewer
          mode={effectiveMode}
          data={effectiveData}
          text={effectiveText}
          viewSchema={effectiveViewSchema}
          activeStatsView={activeStatsView || undefined}
          fieldList={effectiveFieldList}
          tasks={tasks}
          task={detailData.taskId ? tasks.find(t => t.task_id === detailData.taskId) : undefined}
          threadId={threadId}
          maxHeight={480}
        />
      )}
    </Card>
  );
};

export default DetailDataPanel;
