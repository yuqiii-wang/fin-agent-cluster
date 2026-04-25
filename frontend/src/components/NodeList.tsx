import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Flex, Spin, Steps, Tooltip, Typography } from "antd";
import { LoadingOutlined, SyncOutlined, StopOutlined } from "@ant-design/icons";
import type { NodeExecutionInfo, NodeGroup, TaskInfo } from "../types";
import { fetchNodeExecutions } from "../api";
import { JsonViewer } from "./JsonViewer";
import { NODE_LABELS } from "./nodeLabels";
import { useStyles } from "./NodeList.styles";

const { Text } = Typography;

const STEP_STATUS: Record<NodeGroup["status"], "wait" | "process" | "finish" | "error"> = {
  pending: "wait",
  running: "process",
  completed: "finish",
  failed: "error",
  cancelled: "error",
};

interface Props {
  nodes: NodeGroup[];
  threadId: string;
  onNodeClick: (node: NodeGroup) => void;
  tokenStreams?: Record<number, string>;
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
  execution: NodeExecutionInfo | null | "loading";
  /** Status of the selected node — used to show a waiting spinner for non-completed nodes. */
  nodeStatus?: NodeGroup["status"];
  /** Accumulated streaming token text for the running task in this node, if any. */
  streamingText?: string;
}

/** Inline input/output panel for a node, showing the actual state data. */
function NodeInlinePanel({ execution, nodeStatus, streamingText }: NodeInlinePanelProps) {
  const styles = useStyles();
  if (execution === "loading") {
    return <Flex justify="center" style={styles.loadingCenter}><Spin size="small" /></Flex>;
  }

  if (!execution && (nodeStatus === "pending" || nodeStatus === "running")) {
    if (streamingText) {
      return (
        <Flex vertical gap={4} style={styles.streamingContainer}>
          <Flex align="center" gap={6}>
            <SyncOutlined spin style={styles.streamingIcon} />
            <Text type="secondary" style={styles.streamingLabel}>Streaming…</Text>
          </Flex>
          <div style={styles.streamingText}>
            {streamingText}
            <span style={styles.cursorOpacity}>▋</span>
          </div>
        </Flex>
      );
    }
    return (
      <Flex align="center" gap={6} style={styles.waitingContainer}>
        <Spin size="small" />
        <Text type="secondary" style={styles.waitingText}>
          Waiting for node to complete…
        </Text>
      </Flex>
    );
  }

  return (
    <Flex vertical gap={6} style={styles.ioContainer}>
      <div>
        {execution ? (
          <LabelledField label="Input" data={execution.input} />
        ) : (
          <>\n            <Text type="secondary" style={styles.labelText}>Input</Text>
            <div>—</div>
          </>
        )}
      </div>
      <div>
        {execution ? (
          <LabelledField label="Output" data={execution.output} />
        ) : (
          <>
            <Text type="secondary" style={styles.labelText}>Output</Text>
            <div>—</div>
          </>
        )}
      </div>
    </Flex>
  );
}

/** Visual pipeline using antd Steps — click a node to show its input/output below. */
export const NodeList = memo(function NodeList({ nodes, threadId, onNodeClick, tokenStreams = {} }: Props) {
  const styles = useStyles();
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);
  const [executions, setExecutions] = useState<Record<string, NodeExecutionInfo | null>>({});
  const [loading, setLoading] = useState(false);
  const prevStatusRef = useRef<Record<string, string>>({});

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

    console.debug("[NodeList] auto-refresh executions selectedNode=%s threadId=%s", selectedNodeName, threadId);
    setLoading(true);
    fetchNodeExecutions(threadId)
      .then((list) => {
        console.debug("[NodeList] auto-refresh ok count=%d", list.length);
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
    console.debug("[NodeList] click node=%s status=%s threadId=%s", name, node.status, threadId);
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

    console.debug("[NodeList] cached=%o stale=%s", cached, stale);
    if (!(name in executions) || stale) {
      setLoading(true);
      console.debug("[NodeList] fetching executions threadId=%s", threadId);
      fetchNodeExecutions(threadId)
        .then((list) => {
          console.debug("[NodeList] fetchNodeExecutions ok count=%d", list.length, list);
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

  const items = useMemo(() => nodes.map((node) => {
    // Build status-count audit: only include statuses that have at least one task.
    const counts: Partial<Record<TaskInfo["status"], number>> = {};
    for (const t of node.tasks) counts[t.status] = (counts[t.status] ?? 0) + 1;
    const hasRunning = (counts.running ?? 0) > 0;
    // Check if any running task is actively receiving tokens (streaming).
    const isStreaming = node.tasks.some(
      (t) => t.status === "running" && (tokenStreams[t.id] ?? "").length > 0
    );
    const auditParts: string[] = [];
    if (counts.running)   auditParts.push(`${counts.running} running`);
    if (counts.completed) auditParts.push(`${counts.completed} done`);
    if (counts.failed)    auditParts.push(`${counts.failed} failed`);
    if (counts.cancelled) auditParts.push(`${counts.cancelled} cancelled`);
    if (counts.pending)   auditParts.push(`${counts.pending} pending`);
    const descriptionText = auditParts.length > 0 ? auditParts.join(" · ") : `${node.tasks.length} task${node.tasks.length !== 1 ? "s" : ""}`;
    return {
      onClick: () => handleClick(node),
      style: { cursor: "pointer" },
      title: (
        <Tooltip title={`${node.tasks.length} task(s) — click to inspect`}>
          <span style={styles.stepTitle}>{NODE_LABELS[node.node_name] ?? node.node_name}</span>
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
  }), [nodes, tokenStreams, handleClick]);

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
            .map((t) => tokenStreams[t.id] ?? "")
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
          execution={panelData}
          nodeStatus={selectedNodeStatus}
          streamingText={selectedStreamingText || undefined}
        />
      )}
    </>
  );
});

