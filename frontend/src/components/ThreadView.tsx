/**
 * ThreadView — full thread detail panel.
 *
 * Layout (top-to-bottom):
 *  1. Thread status bar
 *  2. Node graph + node detail side panel (Splitter)  [version selector in header]
 *  3. Node timeline
 *  4. Task Gantt
 *
 * When ``sseInfo``/``llmInfo`` are null but the thread is still running
 * (e.g. opened from history), the component bootstraps fresh Centrifugo
 * tokens from the API so live updates keep working.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLatestRef } from '../hooks/refUtils';
import { Alert, Badge, Button, Card, Select, Splitter, Spin, Typography } from 'antd';
import { ArrowLeftOutlined, BranchesOutlined, MenuFoldOutlined, MenuUnfoldOutlined, StopOutlined } from '@ant-design/icons';
import NodeGraph from './NodeGraph';
import NodeDetail from './NodeDetail/index';
import NodeTimeline from './NodeTimeline';
import DataViewer from './DataViewer/index';
import ReExploreModal from './ReExploreModal/index';
import { COLOR_BORDER_PANEL, COLOR_TEXT_MUTED } from '../constants/styleColors';
import { useCentrifugoSse } from '../hooks/useCentrifugoSse';
import { useCentrifugoLlm } from '../hooks/useCentrifugoLlm';
import { useThreadData } from '../hooks/useThreadData';
import { getLlmToken, getSseToken, cancelThread, cancelNode, cancelTask, reExploreNode } from '../api/threads';
import { isThreadTerminal, isThreadActive } from '../constants/lifecycleStatus';
import { STATUS_BADGE } from '../constants/statusColors';
import type { NodeInfo, SseEvent, SseInfo, GraphTopology } from '../types';

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

/** BFS to collect all transitive predecessor node IDs starting from a set of IDs. */
function collectPredecessors(startIds: string[], nodeById: Map<string, NodeInfo>): Set<string> {
  const visited = new Set<string>();
  const queue = [...startIds];
  while (queue.length > 0) {
    const id = queue.shift()!;
    if (visited.has(id)) continue;
    const n = nodeById.get(id);
    if (!n) continue;
    visited.add(id);
    for (const pid of n.prev_node_ids ?? []) {
      if (!visited.has(pid)) queue.push(pid);
    }
  }
  return visited;
}

/** Filter the full merged node list down to what should be visible for a given version.
 *  For fork versions, also includes inner nodes of any shared Subgraph nodes so that
 *  the NodeDetail subgraph panel can display their children.
 *  Topology-only placeholder nodes are included for both v0 and fork versions so that:
 *  - conditional branch peers (same conditional_group) render dashed edges correctly
 *  - +1 depth not-yet-run nodes are visible as grey placeholders */
function getNodesForVersion(allNodes: NodeInfo[], version: number, topology?: GraphTopology | null): NodeInfo[] {
  if (version === 0) {
    // Original run: version-0 real nodes + topology-only placeholders
    return allNodes.filter(n => n.is_topology_only || (n.version ?? 0) === 0);
  }
  // Fork branch: version-N real nodes + shared predecessors
  const realNodes = allNodes.filter(n => !n.is_topology_only);
  const topologyOnlyNodes = allNodes.filter(n => n.is_topology_only);
  const nodeById = new Map(realNodes.map(n => [n.node_id, n]));
  const forkNode = realNodes.find(n => n.is_forked && (n.version ?? 0) === version);
  const versionNNodes = realNodes.filter(n => (n.version ?? 0) === version);
  if (!forkNode) return versionNNodes;
  const sharedIds = collectPredecessors(forkNode.prev_node_ids ?? [], nodeById);
  const sharedNodes = realNodes.filter(n => sharedIds.has(n.node_id));
  // BFS: also include inner nodes (children) of any shared Subgraph nodes.
  const allSharedIds = new Set(sharedIds);
  let frontier = sharedNodes.filter(n => n.type === 'Subgraph').map(n => n.node_id);
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const parentId of frontier) {
      for (const n of realNodes) {
        if (n.parent_node_id === parentId && !allSharedIds.has(n.node_id)) {
          allSharedIds.add(n.node_id);
          if (n.type === 'Subgraph') next.push(n.node_id);
        }
      }
    }
    frontier = next;
  }
  // Also include parallel siblings: nodes that appear in version-N nodes' prev_node_ids
  // and share a parallel_group with a version-N node (but are not themselves version-N).
  // E.g. when analyze_stats is re-explored to v1, conclusion_node v1 references
  // analyze_news_node v0 in its prev_node_ids — it must be included as a shared sibling.
  const parallelGroupsInVersionN = new Set(
    versionNNodes.map(n => n.parallel_group).filter((g): g is string => g != null));
  if (parallelGroupsInVersionN.size > 0) {
    const versionNPrevIds = new Set(versionNNodes.flatMap(n => n.prev_node_ids ?? []));
    for (const n of realNodes) {
      if (
        !allSharedIds.has(n.node_id) &&
        !versionNNodes.some(v => v.node_id === n.node_id) &&
        n.parallel_group != null &&
        parallelGroupsInVersionN.has(n.parallel_group) &&
        versionNPrevIds.has(n.node_id)
      ) {
        allSharedIds.add(n.node_id);
      }
    }
  }
  const allSharedNodes = realNodes.filter(n => allSharedIds.has(n.node_id));
  const includedRealNodes = [...allSharedNodes, ...versionNNodes];

  if (topologyOnlyNodes.length === 0) return includedRealNodes;

  // Build successor set from topology edges so we can reveal +1 depth placeholders.
  const includedNames = new Set(includedRealNodes.map(n => n.node_name));
  const successorTopoNames = new Set<string>();
  if (topology) {
    for (const edge of topology.edges) {
      if (includedNames.has(edge.from_node) && !includedNames.has(edge.to_node)) {
        successorTopoNames.add(edge.to_node);
      }
    }
  }

  // Include topology-only nodes that are:
  //   (a) direct successors of included real nodes (+1 depth not-run nodes), or
  //   (b) conditional peers of an included real node (same conditional_group, needed
  //       so the layout can draw cond-fan-out / cond-fan-in edges correctly), or
  //   (c) parallel peers of an included real node (same parallel_group, needed
  //       so the layout can draw fan-out / fan-in edges correctly).
  const relevantTopoNodes = topologyOnlyNodes.filter(n =>
    successorTopoNames.has(n.node_name) ||
    (n.conditional_group != null &&
      includedRealNodes.some(r => r.conditional_group === n.conditional_group)) ||
    (n.parallel_group != null &&
      includedRealNodes.some(r => r.parallel_group === n.parallel_group)),
  );
  return [...includedRealNodes, ...relevantTopoNodes];
}

const ThreadView: React.FC<Props> = ({ threadId, sseInfo: initialSseInfo, llmInfo: initialLlmInfo, initialTopology, onDone, onStatusChange, onBack }) => {
  const { thread, nodes, tasks, topology, refresh } = useThreadData(threadId, initialTopology ?? null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [tokenStreams, setTokenStreams] = useState<Record<string, string>>({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [detailData, setDetailData] = useState<{ label: string; data: unknown } | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [isStatusBarHovered, setIsStatusBarHovered] = useState(false);

  // Version selector state
  const [activeVersion, setActiveVersion] = useState(0);
  /** When set, switches to this version as soon as its nodes appear in the node list. */
  const [pendingTargetVersion, setPendingTargetVersion] = useState<number | null>(null);

  // Re-explore modal state
  const [reExploreTarget, setReExploreTarget] = useState<NodeInfo | null>(null);
  const [reExploring, setReExploring] = useState(false);

  // Compute the max fork generation present in the node list.
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

  // Nodes filtered for the active version.
  const versionNodes = useMemo(() => getNodesForVersion(nodes, activeVersion, topology), [nodes, activeVersion, topology]);

  // Fork node for the active version (null for version 0).
  const versionForkNode = useMemo(
    () => (activeVersion > 0
      ? nodes.find(n => n.is_forked && (n.version ?? 0) === activeVersion) ?? null
      : null),
    [nodes, activeVersion],
  );

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

  const handleOpenReExplore = useCallback((node: NodeInfo) => {
    setReExploreTarget(node);
  }, []);

  // Derive condition labels for topology-only conditional nodes from the topology edges.
  const reExploreConditions = useMemo(() => {
    if (!reExploreTarget?.is_topology_only || !reExploreTarget.conditional_group || !topology) return undefined;
    const nodeName = reExploreTarget.node_name;
    return topology.edges
      .filter(e => e.to_node === nodeName && e.kind === 'conditional' && e.condition_label)
      .map(e => e.condition_label as string);
  }, [reExploreTarget, topology]);

  const handleReExploreConfirm = useCallback(async (inputOverride?: Record<string, unknown>) => {
    if (!reExploreTarget) return;
    setReExploring(true);
    try {
      const result = await reExploreNode(threadId, reExploreTarget.node_id, inputOverride);
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
  }, [reExploreTarget, threadId, refresh]);

  const onDoneRef = useLatestRef(onDone);
  const onDoneFiredRef = useRef(false);
  const onStatusChangeRef = useLatestRef(onStatusChange);
  const prevStatusRef = useRef<string | undefined>(undefined);

  // Resolved Centrifugo tokens: may come from props (fresh submit) or be
  // bootstrapped from the API when opening a running history thread.
  const [sseInfo, setSseInfo] = useState<SseInfo | null>(initialSseInfo);
  const [llmInfo, setLlmInfo] = useState<SseInfo | null>(initialLlmInfo);
  const [llmEnabled, setLlmEnabled] = useState(() => initialLlmInfo === null);

  const isDone = isThreadTerminal(thread?.status ?? '');
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
        ev.event === 'done' || ev.event === 'stream_complete' || ev.event === 'query_status'
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

  const selectedNode = versionNodes.find((n) => n.node_id === selectedNodeId) ?? null;

  // Version selector options — always include 0 + all versions present in nodes.
  // For v>0, show the fork node name as the label.
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
              size="small" danger icon={<StopOutlined />}
              loading={cancelling === threadId}
              onClick={handleCancelThread}
              style={{ marginLeft: 'auto' }}
            />
          )}
        </div>
        {thread.error && <Alert title={thread.error} type="error" showIcon style={{ marginTop: 8 }} />}
      </Card>

      {/* Node graph + detail panel */}
      <Card
        size="small"
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text strong>Node Graph</Text>
            {maxVersion > 0 && (
              <Select
                size="small"
                value={activeVersion}
                options={versionOptions}
                onChange={setActiveVersion}
                style={{ width: 140 }}
                suffixIcon={<BranchesOutlined />}
              />
            )}
          </div>
        }
        extra={
          <Button
            size="small" type="text"
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
                  nodes={versionNodes}
                  topology={topology}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
                />
              </div>
            </Splitter.Panel>
            <Splitter.Panel>
              <div style={{ padding: 16, overflowY: 'auto', height: '100%', borderLeft: `1px solid ${COLOR_BORDER_PANEL}` }}>
                <NodeDetail
                  node={selectedNode}
                  nodes={versionNodes}
                  tasks={tasks}
                  threadId={threadId}
                  tokenStreams={tokenStreams}
                  threadActive={threadActive}
                  activeVersion={activeVersion}
                  onViewData={handleViewData}
                  onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
                  onCancelNode={handleCancelNode}
                  onCancelTask={handleCancelTask}
                  cancellingId={cancelling}
                  onReExplore={handleOpenReExplore}
                />
              </div>
            </Splitter.Panel>
          </Splitter>
        ) : (
          <div style={{ height: 380 }}>
            <NodeGraph
              nodes={versionNodes}
              topology={topology}
              selectedNodeId={selectedNodeId}
              onSelectNode={(id) => setSelectedNodeId(id === selectedNodeId ? null : id)}
            />
          </div>
        )}
      </Card>

      {/* Timeline */}
      <NodeTimeline
        nodes={versionNodes}
        tasks={tasks}
        selectedNodeId={selectedNodeId}
        onSelectNode={(id) => setSelectedNodeId(id)}
        forkNode={versionForkNode}
      />

      {/* Detail data panel */}
      {detailData ? (
        <Card
          size="small"
          title={<Text strong style={{ fontSize: 12 }}>{detailData.label}</Text>}
          extra={<Button size="small" type="text" onClick={() => setDetailData(null)}>✕</Button>}
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
          <Card size="small" title={<Text strong>Answer</Text>} style={{ borderRadius: 8 }}>
            <DataViewer mode="markdown" text={thread.answer} maxHeight={500} />
          </Card>
        )
      )}

      {/* Re-explore modal */}
      <ReExploreModal
        open={reExploreTarget !== null}
        node={reExploreTarget}
        loading={reExploring}
        onConfirm={handleReExploreConfirm}
        onCancel={() => setReExploreTarget(null)}
        conditions={reExploreConditions}
      />
    </div>
  );
};

export default ThreadView;

