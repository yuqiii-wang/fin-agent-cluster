import { useState } from "react";
import { App, Button, Space, Typography } from "antd";
import { PlayCircleOutlined, StopOutlined } from "@ant-design/icons";
import { cancelTaskByUuid, passTask, cancelTask } from "../../../api";
import type { GraphTask } from "../types";
import type { TaskTypeMeta } from "../../../types";
import { OutputViewer } from "../../OutputViewer/OutputViewer";
import { JsonBlock } from "./JsonBlock";
import { fmtElapsed, taskStatusTag } from "./helpers";

const { Text } = Typography;

export interface TaskDetailProps {
  task: GraphTask;
  threadId?: string;
  taskMeta?: TaskTypeMeta;
  /** Node-level input to show for the first task when task.input is empty. */
  nodeInput?: Record<string, unknown>;
  tokenStream?: string;
  tokenCount?: number;
}

export function TaskDetail({ task, threadId, taskMeta, nodeInput, tokenStream, tokenCount }: TaskDetailProps) {
  const { message } = App.useApp();
  const [cancellingStream, setCancellingStream] = useState(false);
  const [cancellingLlm, setCancellingLlm] = useState(false);
  const [passing, setPassing] = useState(false);

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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "4px 0" }}>
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
        </Space>
      )}

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
