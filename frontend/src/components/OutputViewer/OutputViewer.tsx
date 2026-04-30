/**
 * OutputViewer — smart output renderer for agent task/node output fields.
 *
 * Routing logic:
 *  1. LLM streaming (stream tokens present) → ThinkingStream
 *  2. Task failed                            → ErrorDisplay
 *  3. Task running (LLM, no tokens yet)      → LlmWaitingStatus
 *  4. Task running (non-LLM)                 → RunningDescription (task_key label)
 *  5. Any other completed output             → JsonViewer
 *  6. No output                              → "No output available"
 */

import { Flex, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo, TaskTypeMeta } from "../../types";
import { JsonViewer } from "../JsonViewer";
import { isLlmTask, isPerfTokenTask } from "./helpers";
import {
  ThinkingStream,
  LlmWaitingStatus,
  RunningDescription,
  ErrorDisplay,
} from "./subRenderers";

export { isLlmTask, isPerfTokenTask };

const { Text } = Typography;

interface Props {
  task: TaskInfo;
  /** Accumulated token stream for this task (present for LLM tasks). */
  stream?: string;
  /** LLM provider name (from SSE started event). */
  provider?: string;
  /** Task type metadata from the backend. */
  taskMeta: TaskTypeMeta | null;
}

/**
 * OutputViewer — parent component for all task/node output fields.
 *
 * Automatically picks the right renderer based on task type and output:
 * - LLM streaming  → thinking-style streaming view
 * - OHLCV / quant  → CandlestickChart (when bars are present)
 * - JSON output    → JsonViewer
 */
export function OutputViewer({ task, stream, provider, taskMeta }: Props) {
  if (task.status === "pending") {
    return (
      <Flex align="center" gap={6}>
        <LoadingOutlined style={{ fontSize: 11 }} />
        <Text type="secondary" style={{ fontSize: 12, fontStyle: "italic" }}>
          Waiting to start…
        </Text>
      </Flex>
    );
  }

  if (task.status === "failed") {
    return <ErrorDisplay error={task.output?.error} />;
  }

  const isLlm = taskMeta ? isLlmTask(task.task_key, taskMeta) : false;
  const isPerfSilent = taskMeta ? isPerfTokenTask(task.task_key, taskMeta) : false;

  // Fall back to persisted output.text when no live token stream is available
  const displayStream =
    stream ??
    (typeof task.output?.text === "string" ? (task.output.text as string) : undefined);

  if (displayStream) {
    return (
      <ThinkingStream stream={displayStream} isRunning={task.status === "running"} />
    );
  }

  if (task.status === "running") {
    if (isPerfSilent) {
      return (
        <Flex align="center" gap={6}>
          <LoadingOutlined style={{ fontSize: 11 }} />
          <Text type="secondary" style={{ fontSize: 12, fontStyle: "italic" }}>
            Awaiting backend streaming…
          </Text>
        </Flex>
      );
    }
    return isLlm ? (
      <LlmWaitingStatus provider={provider} />
    ) : (
      <RunningDescription taskKey={task.task_key} />
    );
  }

  const hasOutput =
    task.output != null && Object.keys(task.output).length > 0;

  if (!hasOutput) {
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        No output available.
      </Text>
    );
  }

  return <JsonViewer data={task.output} maxHeight={400} />;
}
