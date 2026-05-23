/**
 * ThreadView — full thread detail panel.
 *
 * Layout (top-to-bottom):
 *  1. Thread status bar
 *  2. Node graph + node detail side panel (Splitter)  [version selector in header]
 *  3. Node timeline
 *  4. Detail data / answer panel
 *
 * When ``sseInfo``/``llmInfo`` are null but the thread is still running
 * (e.g. opened from history), the component bootstraps fresh Centrifugo
 * tokens from the API so live updates keep working.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLatestRef } from '../../hooks/refUtils';
import { Button, Card, Spin, Typography } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import NodeTimeline from '../NodeTimeline';
import DataViewer from '../DataViewer/index';
import { viewTypeToMode } from '../DataViewer/index';
import ReExploreModal from '../ReExploreModal/index';
import ThreadStatusBar from './ThreadStatusBar';
import NodeGraphPanel from './NodeGraphPanel';
import DetailDataPanel from './DetailDataPanel';
import { getNodesForVersion } from './versionUtils';
import { useCentrifugoSse } from '../../hooks/useCentrifugoSse';
import { useCentrifugoLlm } from '../../hooks/useCentrifugoLlm';
import { useThreadData } from '../../hooks/useThreadData';
import { getLlmToken, getSseToken, cancelThread, cancelNode, cancelTask, reExploreNode } from '../../api/threads';
import { evictThreadData } from '../../cache';
import { isThreadTerminal, isThreadActive } from '../../constants/lifecycleStatus';
import type { NodeInfo, SseEvent, SseInfo, GraphTopology } from '../../types';
import type { DetailData } from './types';

const { Text } = Typography;

interface Props {
  threadId: string;
  /** Bootstrap info from submit response, or null when opening a history thread. */
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
  /** Full compiled graph topology from initial submit response (avoids a separate fetch). */
  initialTopology?: GraphTopology | null;
  /** Called once when the thread reaches a terminal state (completed/failed/cancelled). */
  onDone?: () => void;
  /** Called whenever the thread-level status changes (for syncing history sidebar). */
  onStatusChange?: (status: string) => void;
  /** When set, shows a ← back button that navigates back (e.g. to the concurrency grid). */
  onBack?: () => void;
}

const ThreadView: React.FC<Props> = ({ threadId, sseInfo: initialSseInfo, llmInfo: initialLlmInfo, initialTopology, onDone, onStatusChange, onBack }) => {
  const { thread, nodes, tasks, topology, refresh } = useThreadData(threadId, initialTopology ?? null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [tokenStreams, setTokenStreams] = useState<Record<string, string>>({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [detailData, setDetailData] = useState<DetailData | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);

  // Version selector state
  const [activeVersion, setActiveVersion] = useState(0);
  const [pendingTargetVersion, setPendingTargetVersion] = useState<number | null>(null);

  // Re-explore modal state
  const [reExploreTarget, setReExploreTarget] = useState<NodeInfo | null>(null);
  const [reExploring, setReExploring] = useState(false);

  const maxVersion = useMemo(
    () => Math.max(0, ...nodes.filter(n => !n.is_topology_only).map(n => n.version ?? 0)),
    [nodes],
  );

  // Auto-switch to the target version as soon as its fork node appears in the node list.
  useEffect(() => {
    if (pendingTargetVersion === null) return;
    if (nodes.some(n => !n.is_topology_only && (n.version ?? 0) === pendingTargetVersion)) {
      setActiveVersion(pendingTargetVersion);
      setPendingTargetVersion(null);
    }
  }, [pendingTargetVersion, nodes]);

  const versionNodes = useMemo(() => getNodesForVersion(nodes, activeVersion, topology), [nodes, activeVersion, topology]);

  const versionForkNode = useMemo(
    () => (activeVersion > 0
      ? nodes.find(n => n.is_forked && (n.version ?? 0) === activeVersion) ?? null
      : null),
    [nodes, activeVersion],
  );

  const versionOptions = useMemo(() => {
    const versions = new Set([0]);
    const forkNodeNameByVersion = new Map<number, string>();
    for (const n of nodes) {
      if (!n.is_topology_only) {
        versions.add(n.version ?? 0);
        if (n.is_forked) forkNodeNameByVersion.set(n.version ?? 0, n.node_name);
      }
    }
    return Array.from(versions).sort((a, b) => a - b).map(v => ({
      value: v,
      label: v === 0 ? 'v0 original' : `v${v} · ${forkNodeNameByVersion.get(v) ?? 're-explore'}`,
    }));
  }, [nodes]);

  const selectedNode = versionNodes.find((n) => n.node_id === selectedNodeId) ?? null;

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

  const handleViewData = useCallback((
    label: string,
    data: unknown,
    opts?: { mode?: import('../DataViewer/index').DataViewerMode; viewSchema?: Record<string, string>; fieldList?: boolean; nodeContext?: 'input' | 'output'; taskId?: string; activeStatsView?: string },
  ) => {
    setDetailData({ label, data, mode: opts?.mode, viewSchema: opts?.viewSchema, fieldList: opts?.fieldList, nodeContext: opts?.nodeContext, taskId: opts?.taskId, activeStatsView: opts?.activeStatsView });
  }, []);

  // When the user selects a different node while a node's Input/Output panel is open,
  // auto-switch the panel to the new node's corresponding data.
  useEffect(() => {
    if (!selectedNode || !detailData?.nodeContext) return;
    if (detailData.nodeContext === 'input' && selectedNode.input) {
      setDetailData({ label: `${selectedNode.node_name} · Input`, data: selectedNode.input, nodeContext: 'input' });
    } else if (detailData.nodeContext === 'output' && selectedNode.output) {
      setDetailData({
        label: `${selectedNode.node_name} · Output`,
        data: selectedNode.output,
        mode: viewTypeToMode(selectedNode.view_type),
        viewSchema: selectedNode.view_schema as Record<string, string> | undefined,
        fieldList: true,
        nodeContext: 'output',
      });
    }
  }, [selectedNodeId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleOpenReExplore = useCallback((node: NodeInfo) => {
    setReExploreTarget(node);
  }, []);

  const reExplorePrevNodes = useMemo((): NodeInfo[] | undefined => {
    if (!reExploreTarget?.is_topology_only || !topology) return undefined;
    const fromNodeNames = topology.edges
      .filter(e => e.to_node === reExploreTarget.node_name && e.kind === 'conditional')
      .map(e => e.from_node);
    return fromNodeNames
      .map(name => versionNodes.find(n => n.node_name === name && !n.is_topology_only))
      .filter((n): n is NodeInfo => n != null);
  }, [reExploreTarget, topology, versionNodes]);

  const handleReExploreConfirm = useCallback(async (forkNodeId: string, inputOverride?: Record<string, unknown>) => {
    setReExploring(true);
    try {
      const result = await reExploreNode(threadId, forkNodeId, inputOverride);
      // Evict thread cache: the thread is no longer terminal — it's running a new branch.
      evictThreadData(threadId);
      setReExploreTarget(null);
      if (result.fork_version != null) {
        setPendingTargetVersion(result.fork_version);
      }
      refresh();
    } catch {
      // Error surfaced by SSE status change; modal stays open so user can retry.
    } finally {
      setReExploring(false);
    }
  }, [threadId, refresh]);

  const onDoneRef = useLatestRef(onDone);
  const onDoneFiredRef = useRef(false);
  const onStatusChangeRef = useLatestRef(onStatusChange);
  const prevStatusRef = useRef<string | undefined>(undefined);

  const [sseInfo, setSseInfo] = useState<SseInfo | null>(initialSseInfo);
  const [llmInfo, setLlmInfo] = useState<SseInfo | null>(initialLlmInfo);
  const [llmEnabled, setLlmEnabled] = useState(() => initialLlmInfo === null);
  // When a task retry is in flight, keep the SSE connection alive even if the
  // thread itself is terminal.  Cleared once the retried task reaches a terminal state.
  const [retryTaskId, setRetryTaskId] = useState<string | null>(null);

  const isDone = isThreadTerminal(thread?.status ?? '');
  // SSE / LLM hooks stay connected while a retry is in progress.
  const effectiveDone = isDone && retryTaskId === null;
  const threadActive = isThreadActive(thread?.status ?? '');

  useEffect(() => {
    if (isDone && !onDoneFiredRef.current) {
      onDoneFiredRef.current = true;
      onDoneRef.current?.();
    }
  }, [isDone]);

  useEffect(() => {
    setTokenStreams({});
    setSseInfo(initialSseInfo);
    setLlmInfo(initialLlmInfo);
    setLlmEnabled(initialLlmInfo === null);
    setActiveVersion(0);
    setPendingTargetVersion(null);
    onDoneFiredRef.current = false;
    prevStatusRef.current = undefined;
  }, [threadId, initialSseInfo, initialLlmInfo]);

  useEffect(() => {
    if (initialSseInfo || initialLlmInfo || isDone || !thread) return;
    if (isThreadTerminal(thread.status)) return;
    let cancelled = false;
    Promise.all([getSseToken(threadId), getLlmToken(threadId)])
      .then(([sse, llm]) => {
        if (cancelled) return;
        setSseInfo({ ws_url: sse.ws_url, connection_token: sse.connection_token, subscription_token: sse.subscription_token, channel: sse.channel });
        setLlmInfo({ ws_url: llm.ws_url, connection_token: llm.connection_token, subscription_token: llm.subscription_token, channel: llm.channel });
      })
      .catch(() => { /* Non-fatal */ });
    return () => { cancelled = true; };
  }, [threadId, initialSseInfo, initialLlmInfo, isDone, thread]);

  // Clear retryTaskId once the retried task reaches a terminal state.
  useEffect(() => {
    if (!retryTaskId) return;
    const t = tasks.find(t => t.task_id === retryTaskId);
    if (t && new Set(['completed', 'failed', 'cancelled']).has(t.status)) {
      setRetryTaskId(null);
    }
  }, [tasks, retryTaskId]);

  const handleRetryReconnect = useCallback((taskId: string) => {
    setRetryTaskId(taskId);
    // Fetch fresh tokens in case the originals expired while the thread was terminal.
    Promise.all([getSseToken(threadId), getLlmToken(threadId)])
      .then(([sse, llm]) => {
        setSseInfo({ ws_url: sse.ws_url, connection_token: sse.connection_token, subscription_token: sse.subscription_token, channel: sse.channel });
        setLlmInfo({ ws_url: llm.ws_url, connection_token: llm.connection_token, subscription_token: llm.subscription_token, channel: llm.channel });
      })
      .catch(() => { /* Non-fatal: existing tokens may still work */ });
  }, [threadId]);

  useEffect(() => {
    const s = thread?.status;
    if (!s || s === prevStatusRef.current) return;
    prevStatusRef.current = s;
    onStatusChangeRef.current?.(s);
  }, [thread?.status]);

  const handleSseEvent = useCallback(
    (ev: SseEvent) => {
      if (ev.event === 'stream_start') setLlmEnabled(true);
      if (
        ev.event === 'node_status' || ev.event === 'task_status' ||
        ev.event === 'done' || ev.event === 'thread_failed' || ev.event === 'thread_status' ||
        ev.event === 'stream_complete' || ev.event === 'query_status'
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

  useCentrifugoSse({ sseInfo, onEvent: handleSseEvent, done: effectiveDone });
  useCentrifugoLlm({ llmInfo, onToken: handleToken, done: effectiveDone, enabled: llmEnabled });

  if (!thread) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {onBack && (
        <div>
          <Button icon={<ArrowLeftOutlined />} size="small" type="text" onClick={onBack} style={{ paddingLeft: 0 }}>
            Back to Test Grid
          </Button>
        </div>
      )}

      <ThreadStatusBar
        threadId={threadId}
        status={thread.status}
        query={thread.query ?? ''}
        error={thread.error}
        cancelling={cancelling}
        onCancel={handleCancelThread}
      />

      <NodeGraphPanel
        versionNodes={versionNodes}
        topology={topology}
        selectedNodeId={selectedNodeId}
        onSelectNode={setSelectedNodeId}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen(v => !v)}
        activeVersion={activeVersion}
        maxVersion={maxVersion}
        versionOptions={versionOptions}
        onVersionChange={setActiveVersion}
        selectedNode={selectedNode}
        tasks={tasks}
        threadId={threadId}
        tokenStreams={tokenStreams}
        threadActive={threadActive}
        cancelling={cancelling}
        onViewData={handleViewData}
        onCancelNode={handleCancelNode}
        onCancelTask={handleCancelTask}
        onReExplore={handleOpenReExplore}
      />

      <NodeTimeline
        nodes={versionNodes}
        tasks={tasks}
        selectedNodeId={selectedNodeId}
        onSelectNode={(id) => setSelectedNodeId(id)}
        forkNode={versionForkNode}
      />

      {detailData ? (
        <DetailDataPanel
          detailData={detailData}
          onClose={() => setDetailData(null)}
          tasks={tasks}
          nodes={nodes}
          threadId={threadId}
          onRetry={handleRetryReconnect}
        />
      ) : (
        thread.answer && (
          <Card size="small" title={<Text strong>Answer</Text>} style={{ borderRadius: 8 }}>
            {(() => {
              try {
                const parsed = JSON.parse(thread.answer!);
                return <DataViewer mode="json" data={parsed} maxHeight={500} />;
              } catch {
                return <DataViewer mode="markdown" text={thread.answer} maxHeight={500} />;
              }
            })()}
          </Card>
        )
      )}

      <ReExploreModal
        open={reExploreTarget !== null}
        node={reExploreTarget}
        loading={reExploring}
        onConfirm={handleReExploreConfirm}
        onCancel={() => setReExploreTarget(null)}
        prevNodes={reExplorePrevNodes}
      />
    </div>
  );
};

export default ThreadView;
