/**
 * OutputViewer — smart output renderer for agent task/node output fields.
 *
 * Routing logic:
 *  1. LLM streaming (stream tokens present) → StreamingOutput
 *  2. Task failed                            → ErrorDisplay
 *  3. Task running (LLM, no tokens yet)      → LlmWaitingStatus
 *  4. Task running (non-LLM)                 → RunningDescription (task_name label)
 *  5. Candlestick bars present               → CandlestickOutput
 *  6. Any other completed output             → JsonOutput
 *  7. No output                              → "No output available"
 */

import { Flex, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo, TaskTypeMeta } from "../../types";
import { isLlmTask, isPerfTokenTask } from "./helpers";
import {
  LlmWaitingStatus,
  RunningDescription,
  ErrorDisplay,
} from "./subRenderers";
import { StreamingOutput } from "./renderers/StreamingOutput";
import { JsonOutput } from "./renderers/JsonOutput";
import { CandlestickOutput } from "./renderers/CandlestickOutput";
import { StreamingTaskOutput } from "../../services/streaming/core";

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
  /** Total tokens received — shown in streaming lifecycle header. */
  tokenCount?: number;
}

/**
 * OutputViewer — parent component for all task/node output fields.
 *
 * Automatically picks the right renderer based on task type and output:
 * - LLM streaming  → thinking-style streaming view
 * - OHLCV / quant  → CandlestickChart (when bars are present)
 * - JSON output    → JsonOutput
 */
export function OutputViewer({ task, stream, provider, taskMeta, tokenCount }: Props) {
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

  const isLlm = taskMeta ? isLlmTask(task.task_name, taskMeta) : false;
  const isPerfSilent = taskMeta ? isPerfTokenTask(task.task_name, taskMeta) : false;

  // Fall back to persisted output.text when no live token stream is available
  const displayStream =
    stream ??
    (typeof task.output?.text === "string" ? (task.output.text as string) : undefined);

  // Perf-token tasks (token_batch emitters): always render StreamingTaskOutput —
  // it handles both the "awaiting first batch" waiting state and the live stream view.
  if (isPerfSilent) {
    return (
      <StreamingTaskOutput
        stream={displayStream}
        isRunning={task.status === "running"}
        tokenCount={tokenCount}
        status={task.status}
      />
    );
  }

  if (displayStream) {
    return (
      <StreamingOutput
        stream={displayStream}
        isRunning={task.status === "running"}
        tokenCount={tokenCount}
      />
    );
  }

  if (task.status === "running") {
    return isLlm ? (
      <LlmWaitingStatus provider={provider} />
    ) : (
      <RunningDescription taskName={task.task_name} />
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

  if (task.output?.bars && Array.isArray(task.output.bars) && task.output.bars.length > 0) {
    return <CandlestickOutput bars={task.output.bars} />;
  }

  return <JsonOutput data={task.output} />;
}
