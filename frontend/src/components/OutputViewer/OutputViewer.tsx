/**
 * OutputViewer — smart output renderer for agent task/node output fields.
 *
 * Routing logic:
 *  1. Task pending                           → spinner
 *  2. Task failed                            → ErrorDisplay
 *  3. Perf-token task, stream prop provided  → StreamingTaskOutput (parent-managed)
 *  4. Perf-token task, no stream prop        → TaskStreamViewer (self-managed Centrifugo)
 *  5. LLM streaming (stream tokens present)  → StreamingOutput
 *  6. Task running (LLM, no tokens yet)      → LlmWaitingStatus
 *  7. Task running (non-LLM)                 → RunningDescription (task_name label)
 *  8. Candlestick bars present               → CandlestickOutput
 *  9. Any other completed output             → JsonOutput
 * 10. No output                              → "No output available"
 */

import { useState } from "react";
import { Flex, Switch, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo, TaskTypeMeta } from "../../types";
import { isLlmTask, isPerfTokenTask } from "./helpers";
import {
  LlmWaitingStatus,
  RunningDescription,
  ErrorDisplay,
} from "./subRenderers";
import { StreamingOutput } from "./renderers/StreamingOutput";
import { StreamingTaskOutput } from "./renderers/StreamingTaskOutput";
import { TaskStreamViewer } from "./renderers/TaskStreamViewer";
import { JsonOutput } from "./renderers/JsonOutput";
import { CandlestickOutput } from "./renderers/CandlestickOutput";

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
  const [jsonViewEnabled, setJsonViewEnabled] = useState(false);

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

  // Perf-token tasks (token_batch emitters).
  //   • stream prop provided → parent (e.g. useSingleTestSession) is already managing
  //     the Centrifugo subscription; use StreamingTaskOutput to display it.
  //   • stream prop undefined → no external subscription; use TaskStreamViewer so
  //     the user can open/close an on-demand Centrifugo session.
  const isRunning = task.status === "running";
  const hasOutput = task.output != null && Object.keys(task.output).length > 0;

  if (isPerfSilent) {
    if (stream !== undefined) {
      const hasStream = (displayStream?.length ?? 0) > 0;
      return (
        <div>
          <StreamingTaskOutput
            stream={displayStream}
            isRunning={isRunning}
            tokenCount={tokenCount}
            status={task.status}
          />
          {hasStream && (
            <Flex align="center" gap={6} style={{ marginTop: 6 }}>
              <Switch
                size="small"
                checked={jsonViewEnabled}
                onChange={setJsonViewEnabled}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>JSON View</Text>
            </Flex>
          )}
          {jsonViewEnabled && !isRunning && hasOutput && (
            <div style={{ marginTop: 8 }}>
              <JsonOutput data={task.output} />
            </div>
          )}
        </div>
      );
    }
    return (
      <TaskStreamViewer
        task={task}
        completedStream={
          typeof task.output?.text === "string" ? task.output.text : undefined
        }
        tokenCount={tokenCount}
      />
    );
  }

  if (displayStream) {
    return (
      <div>
        <StreamingOutput
          stream={displayStream}
          isRunning={isRunning}
          tokenCount={tokenCount}
        />
        <Flex align="center" gap={6} style={{ marginTop: 6 }}>
          <Switch
            size="small"
            checked={jsonViewEnabled}
            onChange={setJsonViewEnabled}
          />
          <Text type="secondary" style={{ fontSize: 11 }}>JSON View</Text>
        </Flex>
        {jsonViewEnabled && !isRunning && hasOutput && (
          <div style={{ marginTop: 8 }}>
            <JsonOutput data={task.output} />
          </div>
        )}
      </div>
    );
  }

  if (isRunning) {
    return isLlm ? (
      <LlmWaitingStatus provider={provider} />
    ) : (
      <RunningDescription taskName={task.task_name} />
    );
  }

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
