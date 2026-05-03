/**
 * StreamingTaskOutput — unified streaming display for both perf-test and single-test.
 *
 * Handles two states:
 *   1. Awaiting    — isRunning=true, stream is empty/undefined → spinner + label
 *   2. Streaming   — stream text present → StreamingOutput with lifecycle label from status
 *
 * Lifecycle label is derived from `status`:
 *   "ingesting"  → "Ingesting…"
 *   "digesting"  → "Digesting…"
 *   running else → "Streaming…"
 *   not running  → "Completed"
 *
 * Used by:
 *   - OutputViewer (single-test task output for perf-token tasks)
 *   - columns.tsx Streaming Output column (perf-test table)
 */

import { Flex, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { StreamingOutput } from "../../../components/OutputViewer/renderers/StreamingOutput";

const { Text } = Typography;

/** Map a task/session status string to a human-readable lifecycle label. */
function toLifecycleLabel(status: string | undefined, isRunning: boolean): string {
  if (!isRunning) return "Completed";
  if (status === "ingesting") return "Ingesting…";
  if (status === "digesting") return "Digesting…";
  return "Streaming…";
}

interface StreamingTaskOutputProps {
  /** Latest stream text (undefined or "" while awaiting first batch). */
  stream?: string;
  /** Whether the task/session is still running. */
  isRunning: boolean;
  /** Total tokens received — shown as a badge when > 0. */
  tokenCount?: number;
  /**
   * Task or session status string used to derive the lifecycle label.
   * Recognised values: "ingesting" | "digesting" | any running state.
   */
  status?: string;
}

/**
 * Streaming task output component shared by perf-test table and single-test
 * OutputViewer.  Renders an "Awaiting streaming…" spinner when no tokens have
 * arrived yet, and switches to the live StreamingOutput view as soon as the
 * first token batch is received.
 */
export function StreamingTaskOutput({
  stream,
  isRunning,
  tokenCount,
  status,
}: StreamingTaskOutputProps) {
  const hasStream = stream != null && stream.length > 0;

  if (!hasStream && isRunning) {
    return (
      <Flex align="center" gap={6}>
        <LoadingOutlined style={{ fontSize: 11 }} />
        <Text type="secondary" style={{ fontSize: 12, fontStyle: "italic" }}>
          Awaiting streaming…
        </Text>
      </Flex>
    );
  }

  return (
    <StreamingOutput
      stream={stream ?? ""}
      isRunning={isRunning}
      tokenCount={tokenCount}
      lifecycleLabel={toLifecycleLabel(status, isRunning)}
    />
  );
}
