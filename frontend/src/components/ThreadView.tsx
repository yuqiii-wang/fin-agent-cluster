/**
 * ThreadView — full thread detail panel.
 *
 * Layout (top-to-bottom):
 *  1. Thread status bar
 *  2. Node graph + node detail side panel (Splitter)
 *  3. Node timeline
 *  4. Task Gantt
 *
 * When ``sseInfo``/``llmInfo`` are null but the thread is still running
 * (e.g. opened from history), the component bootstraps fresh Centrifugo
 * tokens from the API so live updates keep working.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLatestRef } from '../hooks/refUtils';
import { Alert, Badge, Button, Card, Divider, Splitter, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined, MenuFoldOutlined, MenuUnfoldOutlined, StopOutlined } from '@ant-design/icons';
import NodeGraph from './NodeGraph';
import NodeDetail from './NodeDetail/index';
import NodeTimeline from './NodeTimeline';
import DataViewer from './DataViewer/index';
import { COLOR_BORDER_PANEL, COLOR_TEXT_MUTED } from '../constants/styleColors';
import { useCentrifugoSse } from '../hooks/useCentrifugoSse';
import { useCentrifugoLlm } from '../hooks/useCentrifugoLlm';
import { useThreadData } from '../hooks/useThreadData';
import { getLlmToken, getSseToken, cancelThread, cancelNode, cancelTask } from '../api/threads';
import { TERMINAL_WORK_STATUSES, isThreadTerminal, isThreadActive, isWorkActive } from '../constants/lifecycleStatus';
import { STATUS_BADGE } from '../constants/statusColors';
import type { SseEvent, SseInfo } from '../types';

const { Title, Text } = Typography;

interface Props {
  threadId: string;
  /** Bootstrap info from submit response, or null when opening a history thread. */
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
  /** Called once when the thread reaches a terminal state (completed/failed/cancelled). */
  onDone?: () => void;
  /** Called whenever the thread-level status changes (for syncing history sidebar). */
  onStatusChange?: (status: string) => void;
  /** When set, shows a ← back button that navigates back (e.g. to the concurrency grid). */
  onBack?: () => void;
}

const ThreadView: React.FC<Props> = ({ threadId, sseInfo: initialSseInfo, llmInfo: initialLlmInfo, onDone, onStatusChange, onBack }) => {
  const { thread, nodes, tasks, refresh } = useThreadData(threadId);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [tokenStreams, setTokenStreams] = useState<Record<string, string>>({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [detailData, setDetailData] = useState<{ label: string; data: unknown } | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null); // id being cancelled
  const [isStatusBarHovered, setIsStatusBarHovered] = useState(false);

  const handleCancelThread = useCallback(async () => {
    setCancelling(threadId);
    try { await cancelThread(threadId); } catch { /* SSE will reflect status */ }
    finally { setCancelling(null); }
  }, [threadId]);

  const handleCancelNode = useCallback(async (nodeId: string) => {
    setCancelling(nodeId);
    try { await cancelNode(threadId, nodeId); } catch { /* SSE will reflect status */ }
    finally { setCancelling(null); }
  }, [threadId]);

  const handleCancelTask = useCallback(async (taskId: string, nodeId?: string) => {
    setCancelling(taskId);
    try { await cancelTask(threadId, taskId, nodeId); } catch { /* SSE will reflect status */ }
    finally { setCancelling(null); }
  }, [threadId]);

  const handleViewData = useCallback((label: string, data: unknown) => {
    setDetailData({ label, data });
  }, []);
  const onDoneRef = useLatestRef(onDone);
  const onDoneFiredRef = useRef(false);
  const onStatusChangeRef = useLatestRef(onStatusChange);
  const prevStatusRef = useRef<string | undefined>(undefined);

  // Resolved Centrifugo tokens: may come from props (fresh submit) or be
  // bootstrapped from the API when opening a running history thread.
  const [sseInfo, setSseInfo] = useState<SseInfo | null>(initialSseInfo);
  const [llmInfo, setLlmInfo] = useState<SseInfo | null>(initialLlmInfo);
  // Gate the LLM MQ connection: false until the backend stream_start handshake
  // is confirmed (fresh submit path).  True immediately for history threads
  // so they can recover in-flight tokens via channel history.
  const [llmEnabled, setLlmEnabled] = useState(() => initialLlmInfo === null);

  const isDone = isThreadTerminal(thread?.status ?? '');

  // Fire onDone once when thread reaches a terminal state.
  useEffect(() => {
    if (isDone && !onDoneFiredRef.current) {
      onDoneFiredRef.current = true;
      onDoneRef.current?.();
    }
  }, [isDone]);

  // Reset accumulated token streams and guards whenever we switch thread.
  useEffect(() => {
    setTokenStreams({});
    setSseInfo(initialSseInfo);
    setLlmInfo(initialLlmInfo);
    // Fresh submit: wait for stream_start before connecting to LLM MQ.
    // History / bootstrap: connect immediately and rely on channel recovery.
    setLlmEnabled(initialLlmInfo === null);
    onDoneFiredRef.current = false;
    prevStatusRef.current = undefined;
  }, [threadId, initialSseInfo, initialLlmInfo]);

  // Bootstrap Centrifugo tokens for running history threads (no props provided).
  useEffect(() => {
    if (initialSseInfo || initialLlmInfo || isDone || !thread) return;
    // Only bootstrap when thread is actually running/pending.
    if (isThreadTerminal(thread.status)) return;

    let cancelled = false;
    Promise.all([getSseToken(threadId), getLlmToken(threadId)])
      .then(([sse, llm]) => {
        if (cancelled) return;
        setSseInfo({ ws_url: sse.ws_url, connection_token: sse.connection_token, subscription_token: sse.subscription_token, channel: sse.channel });
        setLlmInfo({ ws_url: llm.ws_url, connection_token: llm.connection_token, subscription_token: llm.subscription_token, channel: llm.channel });
      })
      .catch(() => {
        // Non-fatal — thread may have just completed; polling will reflect that.
      });
    return () => { cancelled = true; };
  }, [threadId, initialSseInfo, initialLlmInfo, isDone, thread]);

  // Bridge: drive history sidebar status from the same polled thread.status so
  // both the ThreadView display and the history entry reflect the same value.
  useEffect(() => {
    const s = thread?.status;
    if (!s || s === prevStatusRef.current) return;
    prevStatusRef.current = s;
    onStatusChangeRef.current?.(s);
  }, [thread?.status]);

  const handleSseEvent = useCallback(
    (ev: SseEvent) => {
      // Backend confirmed it is about to start token streaming — open the
      // LLM MQ channel now so the subscription is ready before the first token.
      if (ev.event === 'stream_start') {
        setLlmEnabled(true);
      }
      // Trigger a data refresh on any lifecycle event.
      if (
        ev.event === 'node_status' ||
        ev.event === 'task_status' ||
        ev.event === 'done' ||
        ev.event === 'stream_complete' ||
        ev.event === 'query_status'
      ) {
        refresh();
      }
    },
    [refresh],
  );

  const handleToken = useCallback(
    (taskId: string, token: string, _seq: number) => {
      setTokenStreams((prev) => ({ ...prev, [taskId]: (prev[taskId] ?? '') + token }));
    },
    [],
  );

  useCentrifugoSse({ sseInfo, onEvent: handleSseEvent, done: isDone });
  useCentrifugoLlm({ llmInfo, onToken: handleToken, done: isDone, enabled: llmEnabled });

  const selectedNode = nodes.find((n) => n.node_id === selectedNodeId) ?? null;

  if (!thread) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Back button — shown when navigating from the concurrency test grid */}
      {onBack && (
        <div>
          <Button
            icon={<ArrowLeftOutlined />}
            size="small"
            type="text"
            onClick={onBack}
            style={{ paddingLeft: 0 }}
          >
            Back to Test Grid
          </Button>
        </div>
      )}
      {/* Status bar */}
      <Card
        size="small"
        style={{ borderRadius: 8 }}
        onMouseEnter={() => setIsStatusBarHovered(true)}
        onMouseLeave={() => setIsStatusBarHovered(false)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Badge status={STATUS_BADGE[thread.status] ?? 'default'} text={thread.status.toUpperCase()} />
          <Text type="secondary" style={{ fontSize: 12 }}>{thread.query}</Text>
          <Text copyable code style={{ fontSize: 10, color: COLOR_TEXT_MUTED }}>{thread.thread_id}</Text>
          {isThreadActive(thread.status) && isStatusBarHovered && (
            <Button
              size="small"
              danger
              icon={<StopOutlined />}
              loading={cancelling === threadId}
              onClick={handleCancelThread}
              style={{ marginLeft: 'auto' }}
            />
          )}
        </div>
        {thread.error && (
          <Alert title={thread.error} type="error" showIcon style={{ marginTop: 8 }} />
        )}
      </Card>

      {/* Node graph + detail panel */}
      <Card
        size="small"
        title={<Text strong>Node Graph</Text>}
        extra={
          <Button
            size="small"
            type="text"
            icon={sidebarOpen ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
            onClick={() => setSidebarOpen((v) => !v)}
            title={sidebarOpen ? 'Hide details' : 'Show details'}
          />
        }
        style={{ borderRadius: 8 }}
        styles={{ body: { padding: 0 } }}
      >
        {sidebarOpen && selectedNode ? (
          <Splitter style={{ height: 380 }}>
            <Splitter.Panel defaultSize="60%" min="40%">
              <div style={{ padding: '8px 0' }}>
                <NodeGraph
                  nodes={nodes}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
                />
              </div>
            </Splitter.Panel>
            <Splitter.Panel>
              <div
                style={{
                  padding: 16,
                  overflowY: 'auto',
                  height: '100%',
                  borderLeft: `1px solid ${COLOR_BORDER_PANEL}`,
                }}
              >
                <NodeDetail
                  node={selectedNode}
                  nodes={nodes}
                  tasks={tasks}
                  threadId={threadId}
                  tokenStreams={tokenStreams}
                  onViewData={handleViewData}
                  onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
                  onCancelNode={handleCancelNode}
                  onCancelTask={handleCancelTask}
                  cancellingId={cancelling}
                />
              </div>
            </Splitter.Panel>
          </Splitter>
        ) : (
          <div style={{ height: 380 }}>
            <NodeGraph
              nodes={nodes}
              selectedNodeId={selectedNodeId}
              onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
            />
          </div>
        )}
      </Card>

      {/* Timeline — clicking a node always selects it for the detail panel */}
      <NodeTimeline
          nodes={nodes}
          tasks={tasks}
          selectedNodeId={selectedNodeId}
          onSelectNode={(id) => setSelectedNodeId(id)}
        />

      {/* Detail data panel (node/task input-output) — takes over the answer slot */}
      {detailData ? (
        <Card
          size="small"
          title={<Text strong style={{ fontSize: 12 }}>{detailData.label}</Text>}
          extra={
            <Button size="small" type="text" onClick={() => setDetailData(null)}>
              ✕
            </Button>
          }
          style={{ borderRadius: 8 }}
        >
          <DataViewer
            mode={typeof detailData.data === 'string' ? 'markdown' : 'json'}
            data={typeof detailData.data !== 'string' ? detailData.data : undefined}
            text={typeof detailData.data === 'string' ? detailData.data : undefined}
            maxHeight={480}
          />
        </Card>
      ) : (
        thread.answer && (
          <Card
            size="small"
            title={<Text strong>Answer</Text>}
            style={{ borderRadius: 8 }}
          >
            <DataViewer mode="markdown" text={thread.answer} maxHeight={500} />
          </Card>
        )
      )}
    </div>
  );
};

export default ThreadView;
