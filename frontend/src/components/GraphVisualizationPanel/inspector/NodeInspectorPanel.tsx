import { useEffect, useState } from "react";
import {
  CloseOutlined,
  PlayCircleOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { App, Button, Collapse, Empty, Space, Tag, Typography } from "antd";
import { cancelNode, fetchTaskMeta, resumeQuery } from "../../../api";
import type { GraphNode, GraphTask } from "../types";
import type { TaskTypeMeta } from "../../../types";
import { JsonOutput } from "../../OutputViewer/renderers/JsonOutput";
import { JsonBlock } from "./JsonBlock";
import { TaskDetail } from "./TaskDetail";
import { fmtElapsed, nodeStatusTag, taskStatusTag } from "./helpers";

const { Text, Title } = Typography;

export interface NodeInspectorPanelProps {
  selectedNodeCx?: number;
  node: GraphNode | null;
  tasks: GraphTask[];
  threadId?: string;
  tokenStreams?: Record<string, string>;
  tokenCounts?: Record<string, number>;
  onClose: () => void;
  onResume?: () => void;
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
  isPendingControl,
}: NodeInspectorPanelProps) {
  const { message } = App.useApp();
  const [cancellingNode, setCancellingNode] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [taskMeta, setTaskMeta] = useState<TaskTypeMeta>();

  useEffect(() => {
    fetchTaskMeta().then(setTaskMeta).catch((err) => {
      console.error("[NodeInspectorPanel] fetchTaskMeta failed", err);
    });
  }, []);

  useEffect(() => {
    if (cancellingNode && node?.status !== "running") setCancellingNode(false);
  }, [node?.status, cancellingNode]);

  useEffect(() => {
    if (resuming && node?.status === "running") setResuming(false);
  }, [node?.status, resuming]);

  if (!node) return null;

  const targetNodeId = (node.node_id as string) || (node.input?.node_id as string) || "";
  const nodeTasks = tasks
    .filter((t) => {
      const taskNodeId = typeof t.input?.node_id === "string" ? t.input.node_id : "";
      if (taskNodeId && targetNodeId) return taskNodeId === targetNodeId;
      return t.node_name === node.node_name;
    })
    .sort((a, b) => a.started_at_ms - b.started_at_ms);
  const firstTaskId = nodeTasks[0]?.task_id;
  const isRunning = node.status === "running";
  const isPaused = node.status === "paused";

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
  }

  async function handleResume() {
    setResuming(true);
    try {
      if (onResume) {
        onResume();
      } else if (threadId) {
        await resumeQuery(threadId);
      }
      message.success("Resume signal sent");
    } catch (e) {
      message.error(`Resume failed: ${e instanceof Error ? e.message : String(e)}`);
      setResuming(false);
    }
  }

  const collapseItems = nodeTasks.map((task) => {
    const isStreaming = taskMeta?.stream_task_names.includes(task.task_name) ?? false;
    return {
      key: task.task_id,
      label: (
        <Space size={8} style={{ width: "100%", justifyContent: "space-between", display: "flex" }}
          data-testid="task-row" data-task-id={task.task_id} data-status={task.status}>
          <Space size={6}>
            <Text strong style={{ fontSize: 12, fontFamily: "monospace" }}>{task.task_name}</Text>
            {isStreaming && <Tag icon={<ThunderboltOutlined />} color="purple" style={{ fontSize: 10 }}>Stream</Tag>}
            {(taskMeta?.llm_task_names.includes(task.task_name) ?? false) && <Tag color="blue" style={{ fontSize: 10 }}>LLM</Tag>}
          </Space>
          <Space size={6}>
            {taskStatusTag(task.status)}
            <Text type="secondary" style={{ fontSize: 11 }}>{fmtElapsed(task.elapsed_ms)}</Text>
          </Space>
        </Space>
      ),
      children: (
        <TaskDetail
          task={task}
          threadId={threadId}
          taskMeta={taskMeta}
          nodeInput={task.task_id === firstTaskId ? (node.input ?? undefined) : undefined}
          tokenStream={tokenStreams?.[task.task_id]}
          tokenCount={tokenCounts?.[task.task_id]}
        />
      ),
    };
  });

  return (
    <div style={{ marginTop: 0, border: "1px solid var(--ant-color-border)", borderRadius: 8, overflow: "hidden", animation: "slideDown 0.18s ease-out" }}>
      {/* Pointer arrow */}
      {selectedNodeCx != null && (
        <div style={{ position: "relative", height: 0, overflow: "visible" }}>
          <div style={{ position: "absolute", left: selectedNodeCx - 8, top: -10, width: 0, height: 0, borderLeft: "8px solid transparent", borderRight: "8px solid transparent", borderBottom: "10px solid var(--ant-color-border)" }} />
          <div style={{ position: "absolute", left: selectedNodeCx - 7, top: -8, width: 0, height: 0, borderLeft: "7px solid transparent", borderRight: "7px solid transparent", borderBottom: "9px solid var(--ant-color-bg-container)" }} />
        </div>
      )}

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", background: "var(--ant-color-bg-elevated)", borderBottom: "1px solid var(--ant-color-border-secondary)" }}>
        <Space size={8}>
          <Title level={5} style={{ margin: 0, fontSize: 13 }}>{node.node_name}</Title>
          {nodeStatusTag(node.status)}
          {node.elapsed_ms != null && <Text type="secondary" style={{ fontSize: 12 }}>{fmtElapsed(node.elapsed_ms)}</Text>}
        </Space>
        <Space size={6}>
          {cancellingNode && (
            <Button danger size="small" icon={<StopOutlined />} loading disabled>Cancel node</Button>
          )}
          {!cancellingNode && isRunning && threadId && node.node_id && (
            <Button danger size="small" icon={<StopOutlined />} onClick={handleCancelNode}>Cancel node</Button>
          )}
          {isPaused && (
            <Button size="small" icon={<PlayCircleOutlined />} loading={resuming || isPendingControl} disabled={isPendingControl} onClick={handleResume}>
              Resume
            </Button>
          )}
          <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} />
        </Space>
      </div>

      {/* Exec ID */}
      <div style={{ padding: "6px 14px", background: "var(--ant-color-bg-elevated)" }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          exec ID: <Text code style={{ fontSize: 10 }}>{node.node_execution_id}</Text>
          {node.node_id && <> · uuid: <Text code style={{ fontSize: 10 }}>{node.node_id}</Text></>}
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
          <Collapse items={collapseItems} size="small" style={{ background: "transparent" }} />
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
