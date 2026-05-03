/**
 * NodeInspectorPanel — inline panel that expands below the DAG SVG when a node
 * is selected.  Tasks are listed as collapsible accordion rows; clicking a task
 * header expands its details inline beneath that row.
 *
 * Replaces the former Drawer-based NodeTaskVisualizationPanel +
 * TaskVisualizationPanel pair.
 */

import {
  CheckCircleFilled,
  CloseCircleFilled,
  CloseOutlined,
  MinusCircleFilled,
  PlayCircleOutlined,
  RetweetOutlined,
  BranchesOutlined,
  StopOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Button,
  Collapse,
  Empty,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useState } from "react";
import { cancelNode, cancelTaskByUuid, passTask, cancelTask, fetchTaskMeta, resumeQuery, pauseQuery } from "../../api";
import type { GraphNode, GraphTask } from "./types";
import { useEffect } from "react";
import type { TaskTypeMeta } from "../../types";
import { OutputViewer } from "../OutputViewer/OutputViewer";
import { JsonOutput } from "../OutputViewer/renderers/JsonOutput";

const { Text, Title } = Typography;

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtElapsed(ms?: number): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function nodeStatusTag(status: GraphNode["status"]) {
  switch (status) {
    case "pending":
      return <Tag color="default">Pending</Tag>;
    case "running":
      return <Tag icon={<SyncOutlined spin />} color="processing">Running</Tag>;
    case "completed":
      return <Tag icon={<CheckCircleFilled />} color="success">Completed</Tag>;
    case "failed":
      return <Tag icon={<CloseCircleFilled />} color="error">Failed</Tag>;
    case "cancelled":
      return <Tag icon={<MinusCircleFilled />} color="warning">Cancelled</Tag>;
    case "paused":
      return <Tag icon={<MinusCircleFilled />} color="purple">Paused</Tag>;
  }
}

function taskStatusTag(status: GraphTask["status"]) {
  switch (status) {
    case "running":
      return <Tag icon={<SyncOutlined spin />} color="processing">Running</Tag>;
    case "completed":
      return <Tag icon={<CheckCircleFilled />} color="success">Completed</Tag>;
    case "failed":
      return <Tag icon={<CloseCircleFilled />} color="error">Failed</Tag>;
    case "cancelled":
      return <Tag icon={<MinusCircleFilled />} color="warning">Cancelled</Tag>;
    case "paused":
      return <Tag icon={<MinusCircleFilled />} color="purple">Paused</Tag>;
  }
}

// ── JsonBlock ─────────────────────────────────────────────────────────────

function JsonBlock({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2);
  if (!text || text === "{}" || text === "null") {
    return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
  }
  return (
    <pre
      style={{
        fontSize: 11,
        background: "var(--ant-color-bg-layout)",
        border: "1px solid var(--ant-color-border)",
        borderRadius: 6,
        padding: "8px 10px",
        overflowX: "auto",
        maxHeight: 260,
        overflowY: "auto",
        margin: 0,
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
      }}
    >
      {text}
    </pre>
  );
}

// ── TaskAccordionItem (rendered inside Collapse.Panel children) ───────────

interface TaskDetailProps {
  task: GraphTask;
  threadId?: string;
  taskMeta?: TaskTypeMeta;
  /** Node-level input to show for the first task when task.input is empty. */
  nodeInput?: Record<string, unknown>;
  /** Live token stream for this task (LLM tasks). */
  tokenStream?: string;
  /** Total tokens received for this task. */
  tokenCount?: number;
}

function TaskDetail({ task, threadId, taskMeta, nodeInput, tokenStream, tokenCount }: TaskDetailProps) {
  const [cancellingStream, setCancellingStream] = useState(false);
  const [cancellingLlm, setCancellingLlm] = useState(false);
  const [passing, setPassing] = useState(false);
  const [pausing, setPausing] = useState(false);

  const isRunning = task.status === "running";
  const isStreaming = taskMeta?.stream_task_names.includes(task.task_name) ?? false;
  const isLlm = taskMeta?.llm_task_names.includes(task.task_name) ?? false;

  async function handleCancelStream() {
    if (!threadId) return;
    setCancellingStream(true);
    try {
      await cancelTaskByUuid(threadId, task.task_id);
      message.success("Cancel signal sent");
    } catch (e) {
      message.error(`Cancel failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCancellingStream(false);
    }
  }

  async function handleCancelLlm() {
    setCancellingLlm(true);
    try {
      await cancelTask(task.task_id);
      message.success("Cancel signal sent");
    } catch (e) {
      message.error(`Cancel failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCancellingLlm(false);
    }
  }

  async function handlePass() {
    setPassing(true);
    try {
      await passTask(task.task_id);
      message.success("Pass signal sent");
    } catch (e) {
      message.error(`Pass failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPassing(false);
    }
  }

  async function handlePause() {
    if (!threadId) return;
    setPausing(true);
    try {
      await pauseQuery(threadId);
      message.success("Pause signal sent — graph will pause at next checkpoint");
    } catch (e) {
      message.error(`Pause failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPausing(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "4px 0" }}>
      {/* Metadata row */}
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>Task ID</Text>
          <br />
          <Text style={{ fontSize: 12, fontFamily: "monospace" }}>{task.task_id}</Text>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>Elapsed</Text>
          <br />
          <Text style={{ fontSize: 12 }}>{fmtElapsed(task.elapsed_ms)}</Text>
        </div>
        {task.ended_at_ms && (
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>Ended at</Text>
            <br />
            <Text style={{ fontSize: 12 }}>{new Date(task.ended_at_ms).toISOString()}</Text>
          </div>
        )}
      </div>

      {/* Cancel / Pass / Pause buttons — only when running */}
      {isRunning && (
        <Space size="small">
          {isStreaming && threadId && (
            <Button danger size="small" icon={<StopOutlined />} loading={cancellingStream} onClick={handleCancelStream}>
              Cancel
            </Button>
          )}
          {isLlm && (
            <Button danger size="small" icon={<StopOutlined />} loading={cancellingLlm} onClick={handleCancelLlm}>
              Cancel
            </Button>
          )}
          {(isStreaming || isLlm) && (
            <Button size="small" icon={<PlayCircleOutlined />} loading={passing} onClick={handlePass}>
              Pass
            </Button>
          )}
          {threadId && (
            <Button size="small" icon={<MinusCircleFilled />} loading={pausing} onClick={handlePause}>
              Pause
            </Button>
          )}
        </Space>
      )}

      {/* Input section — fall back to node input for the first task when task.input is empty */}
      {(() => {
        const effectiveInput =
          task.input && Object.keys(task.input).length > 0
            ? task.input
            : nodeInput && Object.keys(nodeInput).length > 0
              ? nodeInput
              : null;
        if (!effectiveInput) return null;
        return (
          <div>
            <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>Input</Text>
            <JsonBlock value={effectiveInput} />
          </div>
        );
      })()}

      {/* Output section */}
      <div>
        <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>
          {isStreaming ? "Streaming Output" : "Output"}
        </Text>
        <OutputViewer
          task={task as any}
          taskMeta={taskMeta || null}
          stream={tokenStream}
          tokenCount={tokenCount}
        />
      </div>
    </div>
  );
}

// ── NodeInspectorPanel ─────────────────────────────────────────────────────

interface NodeInspectorPanelProps {
  /** X center of the selected node circle in SVG coordinates (for the pointer arrow). */
  selectedNodeCx?: number;
  node: GraphNode | null;
  tasks: GraphTask[];
  threadId?: string;
  /** Accumulated LLM token streams keyed by task_id. */
  tokenStreams?: Record<string, string>;
  /** Total token counts keyed by task_id. */
  tokenCounts?: Record<string, number>;
  onClose: () => void;
  /** Called when the user clicks Resume — must re-open the SSE stream. */
  onResume?: () => void;
  /** Called when the user clicks Replay — opens SSE then calls replay API. */
  onReplay?: (nodeName: string) => void;
  /** Called when the user clicks Fork — forks to a new independent thread from this node's checkpoint. */
  onFork?: (nodeName: string) => void;
  /** True while a control action (pause/resume/replay/fork/cancel) is awaiting backend ack. */
  isPendingControl?: boolean;
}

export function NodeInspectorPanel({
  selectedNodeCx,
  node,
  tasks,
  threadId,
  tokenStreams,
  tokenCounts,
  onClose,
  onResume,
  onReplay,
  onFork,
  isPendingControl,
}: NodeInspectorPanelProps) {
  const [cancellingNode, setCancellingNode] = useState(false);
  const [pausingNode, setPausingNode] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [taskMeta, setTaskMeta] = useState<TaskTypeMeta>();

  useEffect(() => {
    fetchTaskMeta().then(setTaskMeta).catch((err) => {
      console.error("[NodeInspectorPanel] fetchTaskMeta failed", err);
    });
  }, []);

  // Clear cancel spinner once the node is no longer running (status driven by SSE).
  useEffect(() => {
    if (cancellingNode && node?.status !== "running") {
      setCancellingNode(false);
    }
  }, [node?.status, cancellingNode]);

  // Clear pause spinner once the node has transitioned away from running (SSE ack).
  useEffect(() => {
    if (pausingNode && node?.status !== "running") {
      setPausingNode(false);
    }
  }, [node?.status, pausingNode]);

  // Clear resume spinner once the node is running again (SSE ack).
  useEffect(() => {
    if (resuming && node?.status === "running") {
      setResuming(false);
    }
  }, [node?.status, resuming]);

  if (!node) return null;

  const targetNodeId = (node.node_id as string) || (node.input?.node_id as string) || "";
  const nodeTasks = tasks
    .filter((t) => {
      const taskNodeId = typeof t.input?.node_id === "string" ? t.input.node_id : "";
      if (taskNodeId && targetNodeId) {
        return taskNodeId === targetNodeId;
      }
      return t.node_name === node.node_name;
    })
    .sort((a, b) => a.started_at_ms - b.started_at_ms);
  const firstTaskId = nodeTasks[0]?.task_id;
  const isRunning = node.status === "running";

  async function handleCancelNode() {
    if (!threadId || !node?.node_id) return;
    setCancellingNode(true);
    try {
      await cancelNode(threadId, node.node_id);
      message.success("Cancel signal sent to node");
    } catch (e) {
      message.error(`Cancel failed: ${e instanceof Error ? e.message : String(e)}`);
      setCancellingNode(false);
    }
    // Do NOT clear cancellingNode here — the useEffect clears it when node.status changes.
  }

  async function handlePauseNode() {
    if (!threadId) return;
    setPausingNode(true);
    try {
      await pauseQuery(threadId);
      message.success("Pause signal sent — graph will pause at next checkpoint");
    } catch (e) {
      message.error(`Pause failed: ${e instanceof Error ? e.message : String(e)}`);
      setPausingNode(false); // only clear on error; success clears via useEffect
    }
    // Do NOT clear pausingNode here — the useEffect clears it when node.status changes.
  }

  async function handleResume() {
    setResuming(true);
    try {
      if (onResume) {
        onResume();
      } else if (threadId) {
        // Fallback: direct API call (stream not re-opened — legacy).
        await resumeQuery(threadId);
      }
      message.success("Resume signal sent");
    } catch (e) {
      message.error(`Resume failed: ${e instanceof Error ? e.message : String(e)}`);
      setResuming(false); // only clear on error; success clears via useEffect
    }
    // Do NOT clear resuming here — the useEffect clears it when node becomes running.
  }

  async function handleReplay() {
    if (!node?.node_name) return;
    try {
      if (onReplay) {
        // onReplay opens the SSE stream then calls replayFromNode once subscribed.
        // The in-flight guard in useSingleTestSession prevents duplicate calls.
        onReplay(node.node_name);
      }
      message.success(`Replay started from node "${node.node_name}"`);
    } catch (e) {
      message.error(`Replay failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleFork() {
    if (!node?.node_name) return;
    try {
      if (onFork) {
        onFork(node.node_name);
      }
      message.success(`Fork started from node "${node.node_name}"`);
    } catch (e) {
      message.error(`Fork failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // Build Collapse items from tasks
  const collapseItems = nodeTasks.map((task) => {
    const isStreaming = taskMeta?.stream_task_names.includes(task.task_name) ?? false;
    return {
      key: task.task_id,
      label: (
        <Space
          size={8}
          style={{ width: "100%", justifyContent: "space-between", display: "flex" }}
          data-testid="task-row"
          data-task-id={task.task_id}
          data-status={task.status}
        >
          <Space size={6}>
            <Text strong style={{ fontSize: 12, fontFamily: "monospace" }}>
              {task.task_name}
            </Text>
            {isStreaming && <Tag icon={<ThunderboltOutlined />} color="purple" style={{ fontSize: 10 }}>Stream</Tag>}
            {(taskMeta?.llm_task_names.includes(task.task_name) ?? false) && <Tag color="blue" style={{ fontSize: 10 }}>LLM</Tag>}
          </Space>
          <Space size={6}>
            {taskStatusTag(task.status)}
            <Text type="secondary" style={{ fontSize: 11 }}>{fmtElapsed(task.elapsed_ms)}</Text>
          </Space>
        </Space>
      ),
      children: <TaskDetail task={task} threadId={threadId} taskMeta={taskMeta} nodeInput={task.task_id === firstTaskId ? (node.input ?? undefined) : undefined} tokenStream={tokenStreams?.[task.task_id]} tokenCount={tokenCounts?.[task.task_id]} />,
    };
  });

  const pointerLeft = selectedNodeCx != null ? selectedNodeCx : undefined;

  return (
    <div
      style={{
        marginTop: 0,
        border: "1px solid var(--ant-color-border)",
        borderRadius: 8,
        overflow: "hidden",
        animation: "slideDown 0.18s ease-out",
      }}
    >
      {/* Pointer arrow pointing up toward the selected node */}
      {pointerLeft != null && (
        <div
          style={{
            position: "relative",
            height: 0,
            overflow: "visible",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: pointerLeft - 8,
              top: -10,
              width: 0,
              height: 0,
              borderLeft: "8px solid transparent",
              borderRight: "8px solid transparent",
              borderBottom: "10px solid var(--ant-color-border)",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: pointerLeft - 7,
              top: -8,
              width: 0,
              height: 0,
              borderLeft: "7px solid transparent",
              borderRight: "7px solid transparent",
              borderBottom: "9px solid var(--ant-color-bg-container)",
            }}
          />
        </div>
      )}

      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          background: "var(--ant-color-bg-elevated)",
          borderBottom: "1px solid var(--ant-color-border-secondary)",
        }}
      >
        <Space size={8}>
          <Title level={5} style={{ margin: 0, fontSize: 13 }}>{node.node_name}</Title>
          {nodeStatusTag(node.status)}
          {node.elapsed_ms != null && (
            <Text type="secondary" style={{ fontSize: 12 }}>{fmtElapsed(node.elapsed_ms)}</Text>
          )}
        </Space>
        <Space size={6}>
          {cancellingNode && (
            <Button danger size="small" icon={<StopOutlined />} loading disabled>
              Cancel node
            </Button>
          )}
          {!cancellingNode && isRunning && threadId && node.node_id && (
            <Button
              danger
              size="small"
              icon={<StopOutlined />}
              onClick={handleCancelNode}
            >
              Cancel node
            </Button>
          )}
          {!cancellingNode && isRunning && threadId && (
            <Button
              size="small"
              icon={<MinusCircleFilled />}
              loading={pausingNode}
              onClick={handlePauseNode}
            >
              Pause
            </Button>
          )}
          {!cancellingNode && node.status === "paused" && threadId && (
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              loading={resuming}
              onClick={handleResume}
            >
              Resume
            </Button>
          )}
          {!cancellingNode && node.status === "completed" && onReplay && (
            <Button
              size="small"
              icon={<RetweetOutlined />}
              onClick={handleReplay}
              loading={isPendingControl}
              disabled={isPendingControl}
              data-testid="replay-btn"
            >
              Replay
            </Button>
          )}
          {!cancellingNode && node.status === "completed" && onFork && (
            <Button
              size="small"
              icon={<BranchesOutlined />}
              onClick={handleFork}
              loading={isPendingControl}
              disabled={isPendingControl}
              data-testid="fork-btn"
            >
              Fork
            </Button>
          )}
          <Button
            type="text"
            size="small"
            icon={<CloseOutlined />}
            onClick={onClose}
          />
        </Space>
      </div>

      {/* Node exec ID */}
      <div style={{ padding: "6px 14px", background: "var(--ant-color-bg-elevated)" }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          exec ID: <Text code style={{ fontSize: 10 }}>{node.node_execution_id}</Text>
          {node.node_id && (
            <> · uuid: <Text code style={{ fontSize: 10 }}>{node.node_id}</Text></>
          )}
        </Text>
      </div>

      {/* Node input / output */}
      {(node.input || node.output) && (
        <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--ant-color-border-secondary)", display: "flex", flexDirection: "column", gap: 8 }}>
          {node.input && Object.keys(node.input).length > 0 && (
            <div>
              <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>Node Input</Text>
              <JsonBlock value={node.input} />
            </div>
          )}
          {node.output && Object.keys(node.output).length > 0 && (
            <div>
              <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>Node Output</Text>
              <JsonOutput data={node.output} />
            </div>
          )}
        </div>
      )}

      {/* Task list */}
      <div style={{ padding: "10px 14px" }}>
        {nodeTasks.length === 0 ? (
          <Empty description="No tasks yet" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: "12px 0" }} />
        ) : (
          <Collapse
            items={collapseItems}
            size="small"
            style={{ background: "transparent" }}
          />
        )}
      </div>

      <style>{`
        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
