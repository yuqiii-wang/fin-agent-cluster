import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Flex, Spin, Steps, Tooltip, Typography } from "antd";
import { LoadingOutlined, PlayCircleOutlined, StopOutlined, SyncOutlined } from "@ant-design/icons";
import type { NodeExecutionInfo, NodeGroup, TaskInfo, TaskTypeMeta } from "../types";
import { cancelNode, fetchNodeExecutions, fetchTaskMeta, resumeQuery } from "../api";
import { JsonViewer } from "./JsonViewer";
import { OutputViewer } from "./OutputViewer";

import { useStyles } from "./NodeList.styles";
import { getErrorDescription } from "../services/streaming";

const { Text } = Typography;

const STEP_STATUS: Record<NodeGroup["status"], "wait" | "process" | "finish" | "error"> = {
  pending: "wait",
  running: "process",
  completed: "finish",
  failed: "error",
  cancelled: "error",
  paused: "wait",
};

interface Props {
  nodes: NodeGroup[];
  threadId: string;
  onNodeClick: (node: NodeGroup) => void;
  tokenStreams?: Record<string, string>;
  /** Whether the parent query is still running (enables per-node cancel). */
  queryRunning?: boolean;
  /** Whether the parent query is cancelled/failed (enables resume). */
  queryResumable?: boolean;
}

/** Field with label + JsonViewer (copy button is built into JsonViewer). */
function LabelledField({ label, data }: { label: string; data: unknown }) {
  const styles = useStyles();
  return (
    <div>
      <Text type="secondary" style={styles.labelText}>{label}</Text>
      <JsonViewer data={data} maxHeight={400} />
    </div>
  );
}

interface NodeInlinePanelProps {
  node: NodeGroup;
  execution: NodeExecutionInfo | null | "loading";
  taskMeta: TaskTypeMeta | null;
  tokenStreams: Record<string, string>;
  nodeStatus?: NodeGroup["status"];
  streamingText?: string;
}

/** Inline task list panel for a node, mapping each task to an OutputViewer component. */
function NodeInlinePanel({ node, taskMeta, tokenStreams, execution, nodeStatus, streamingText }: NodeInlinePanelProps) {
  const styles = useStyles();

  return (
    <Flex vertical gap={6} style={styles.ioContainer}>
      {node.tasks.length === 0 ? (
        <Text type="secondary" style={styles.waitingText}>
          No tasks found for this node.
        </Text>
      ) : (
        node.tasks.map((task) => (
          <div key={task.task_id} style={{ marginBottom: 12 }}>
            <Text type="secondary" style={styles.labelText}>
              {task.task_name} <span style={{ fontSize: 10, opacity: 0.5 }}>({task.task_id})</span>
            </Text>
            <div style={{ marginTop: 6 }}>
              <OutputViewer
                task={task}
                stream={tokenStreams[task.task_id]}
                taskMeta={taskMeta}
              />
            </div>
          </div>
        ))
      )}
    </Flex>
  );
}

/** Visual pipeline using antd Steps — click a node to show its input/output below. */
export const NodeList = memo(function NodeList({ nodes, threadId, onNodeClick, tokenStreams = {}, queryRunning = false, queryResumable = false }: Props) {
  const styles = useStyles();
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);
  const [executions, setExecutions] = useState<Record<string, NodeExecutionInfo | null>>({});
  const [loading, setLoading] = useState(false);
  // cancellingNodes: node_ids currently waiting for the backend to confirm cancellation.
  const [cancellingNodes, setCancellingNodes] = useState<Set<string>>(new Set());
  // resuming: true while the resume API call is in-flight, waiting for query_status: running.
  const [resuming, setResuming] = useState(false);
  const prevStatusRef = useRef<Record<string, string>>({});

  const [taskMeta, setTaskMeta] = useState<TaskTypeMeta | null>(null);
  useEffect(() => {
    fetchTaskMeta().then(setTaskMeta).catch((err) => {
      console.error("[NodeList] fetchTaskMeta failed", err);
    });
  }, []);

  /** Re-fetch execution data for the selected node when it transitions to completed. */
  useEffect(() => {
    let needsRefresh = false;
    for (const node of nodes) {
      const prev = prevStatusRef.current[node.node_name];
      if (
        prev !== undefined &&
        prev !== "completed" &&
        node.status === "completed" &&
        node.node_name === selectedNodeName
      ) {
        needsRefresh = true;
      }
      prevStatusRef.current[node.node_name] = node.status;
    }
    if (!needsRefresh || !selectedNodeName) return;

    setLoading(true);
    fetchNodeExecutions(threadId)
      .then((list) => {
        const map: Record<string, NodeExecutionInfo | null> = {};
        for (const e of list) map[e.node_name] = e;
        setExecutions(map);
      })
      .catch((err) => {
        console.error("[NodeList] auto-refresh fetchNodeExecutions failed", err);
      })
      .finally(() => setLoading(false));
  }, [nodes, selectedNodeName, threadId]);

  const handleClick = useCallback((node: NodeGroup) => {
    const name = node.node_name;
    if (selectedNodeName === name) {
      setSelectedNodeName(null);
      onNodeClick(node);
      return;
    }
    setSelectedNodeName(name);
    onNodeClick(node);

    // Fetch if not cached, or if we have a stale entry with empty output for a completed node
    const cached = executions[name];
    const stale = cached !== undefined && node.status === "completed" &&
      Object.keys(cached?.output ?? {}).length === 0;

    if (!(name in executions) || stale) {
      setLoading(true);
      fetchNodeExecutions(threadId)
        .then((list) => {
          const map: Record<string, NodeExecutionInfo | null> = {};
          for (const e of list) map[e.node_name] = e;
          setExecutions(map);
        })
        .catch((err) => {
          console.error("[NodeList] fetchNodeExecutions failed", err);
          setExecutions((prev) => ({ ...prev, [name]: null }));
        })
        .finally(() => setLoading(false));
    }
  }, [selectedNodeName, onNodeClick, executions, threadId]);

  const handleCancelNode = useCallback((e: React.MouseEvent, node: NodeGroup) => {
    e.stopPropagation();
    if (!node.node_id) return;
    setCancellingNodes((prev) => new Set(prev).add(node.node_id!));
    cancelNode(threadId, node.node_id).catch((err) => {
      console.error("[NodeList] cancelNode failed", err);
      setCancellingNodes((prev) => {
        const next = new Set(prev);
        next.delete(node.node_id!);
        return next;
      });
    });
    // Note: spinner stays until SSE delivers node_status: cancelled (see effect below).
  }, [threadId]);

  /**
   * Clear the cancelling-node spinner once the QUERY transitions to cancelled/failed
   * (i.e. the done event confirmed the full stop).  We intentionally wait for
   * queryResumable rather than node.status === "cancelled" so the spinner stays
   * visible through the brief window between node_status and done events.
   */
  useEffect(() => {
    if (cancellingNodes.size === 0) return;
    if (queryResumable) {
      setCancellingNodes(new Set());
    }
  }, [queryResumable, cancellingNodes.size]);

  const handleResume = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setResuming(true);
    resumeQuery(threadId).catch((err) => {
      console.error("[NodeList] resumeQuery failed", err);
      setResuming(false);
    });
    // Spinner clears when SSE delivers query_status: running (queryRunning becomes true).
  }, [threadId]);

  /** Clear the resume spinner once the backend transitions the query back to running. */
  useEffect(() => {
    if (queryRunning) setResuming(false);
  }, [queryRunning]);

  const items = useMemo(() => nodes.map((node) => {
    // Build status-count audit: only include statuses that have at least one task.
    const counts: Partial<Record<TaskInfo["status"], number>> = {};
    for (const t of node.tasks) counts[t.status] = (counts[t.status] ?? 0) + 1;
    const hasRunning = (counts.running ?? 0) > 0;
    // Check if any running task is actively receiving tokens (streaming).
    const isStreaming = node.tasks.some(
      (t) => t.status === "running" && (tokenStreams[t.task_id] ?? "").length > 0
    );
    const auditParts: string[] = [];
    if (counts.running)   auditParts.push(`${counts.running} running`);
    if (counts.completed) auditParts.push(`${counts.completed} done`);
    if (counts.failed)    auditParts.push(`${counts.failed} failed`);
    if (counts.cancelled) auditParts.push(`${counts.cancelled} cancelled`);
    if (counts.pending)   auditParts.push(`${counts.pending} pending`);
    const descriptionText = auditParts.length > 0 ? auditParts.join(" · ") : `${node.tasks.length} task${node.tasks.length !== 1 ? "s" : ""}`;

    // Collect error messages from failed tasks for hover tooltip.
    const failedErrors = node.tasks
      .filter((t) => t.status === "failed")
      .map((t) => getErrorDescription(t.error_code, t.error_description) ?? t.error)
      .filter((msg): msg is string => !!msg);
    const errorTooltip = failedErrors.length > 0 ? failedErrors.join("\n") : null;

    const canCancelNode = queryRunning && node.status === "running" && !!node.node_id;
    const isCancellingNode = !!node.node_id && cancellingNodes.has(node.node_id);
    // Show Resume button when query is resumable and this node is the one that was cancelled or paused.
    // "Resuming" a cancelled/paused node = resuming the whole thread from the last checkpoint.
    const isCancelledNode = node.status === "cancelled" || node.status === "paused";
    const showResume = queryResumable && isCancelledNode;
    // Show spinner while cancel is in-flight (stays until queryResumable=true, not just node_status).
    const showCancelSpinner = isCancellingNode && !showResume;

    return {
      onClick: () => handleClick(node),
      style: { cursor: "pointer" },
      title: (
        <Tooltip
          title={errorTooltip ?? `${node.tasks.length} task(s) — click to inspect`}
          color={errorTooltip ? "red" : undefined}
          overlayStyle={errorTooltip ? { maxWidth: 400, whiteSpace: "pre-wrap" } : undefined}
        >
          <Flex align="center" gap={4}>
            <span style={styles.stepTitle}>{node.node_name}</span>
            {showCancelSpinner ? (
              <Spin size="small" indicator={<LoadingOutlined style={{ fontSize: 12 }} spin />} />
            ) : canCancelNode ? (
              <Tooltip title="Cancel this node">
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  onClick={(e) => handleCancelNode(e, node)}
                  style={{ minWidth: 0, padding: "0 2px", height: 18, lineHeight: "18px" }}
                />
              </Tooltip>
            ) : null}
            {showResume && (
              <Tooltip title="Resume from last checkpoint">
                <Button
                  type="text"
                  size="small"
                  icon={<PlayCircleOutlined />}
                  loading={resuming}
                  onClick={handleResume}
                  style={{ minWidth: 0, padding: "0 2px", height: 18, lineHeight: "18px", color: "inherit" }}
                />
              </Tooltip>
            )}
          </Flex>
        </Tooltip>
      ),
      description: (
        <span style={styles.stepDesc}>
          {isStreaming
            ? <SyncOutlined spin style={styles.streamingRunningIcon} />
            : hasRunning && <LoadingOutlined style={styles.runningIcon} />
          }
          {isStreaming ? <span style={styles.streamingColorText}>streaming…</span> : descriptionText}
        </span>
      ),
      status: STEP_STATUS[node.status],
      ...(node.status === "cancelled" ? { icon: <StopOutlined style={styles.cancelledIcon} /> } : {}),
    };
  }), [nodes, tokenStreams, handleClick, queryRunning, queryResumable, cancellingNodes, resuming, handleCancelNode, handleResume]);

  const panelData: NodeExecutionInfo | null | "loading" =
    selectedNodeName === null
      ? null
      : loading
      ? "loading"
      : executions[selectedNodeName] ?? null;

  const selectedNode = selectedNodeName
    ? nodes.find((n) => n.node_name === selectedNodeName)
    : undefined;
  const selectedNodeStatus = selectedNode?.status;

  // Accumulate streaming token text for the selected node's running tasks.
  const selectedStreamingText = useMemo(
    () =>
      selectedNode
        ? selectedNode.tasks
            .filter((t) => t.status === "running")
            .map((t) => tokenStreams[t.task_id] ?? "")
            .join("")
        : "",
    [selectedNode, tokenStreams],
  );

  return (
    <>
      <Steps
        size="small"
        direction="horizontal"
        responsive={false}
        style={styles.steps}
        items={items}
      />
      {selectedNodeName !== null && (
        <NodeInlinePanel
          node={selectedNode!}
          execution={panelData}
          nodeStatus={selectedNodeStatus}
          streamingText={selectedStreamingText || undefined}
          taskMeta={taskMeta}
          tokenStreams={tokenStreams}
        />
      )}
    </>
  );
});

