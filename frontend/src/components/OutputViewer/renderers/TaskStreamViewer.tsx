/**
 * TaskStreamViewer — on-demand streaming viewer for perf-token tasks in OutputViewer.
 *
 * Renders a Show / Hide toggle.  Opening creates a Centrifugo subscription to
 * thread:{task.thread_id}; closing tears it down.
 *
 * Phases:
 *   connecting  → spinner "Awaiting streaming…" while waiting for Centrifugo +
 *                 first token batch (SSE ack + WebSocket handshake)
 *   streaming   → live StreamingOutput with "Streaming…" label
 *   done        → StreamingOutput with "Completed" label + check icon
 *   error       → error note
 *
 * For completed tasks with stored output.text the subscription is skipped and
 * the completed output is rendered directly.
 */

import { useState } from "react";
import { Button, Flex, Switch, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo } from "../../../types";
import { StreamingOutput } from "./StreamingOutput";
import { JsonOutput } from "./JsonOutput";
import { useTaskStream } from "../../../services/streaming/core/useTaskStream";
import { enableTaskStream } from "../../../api";

const { Text } = Typography;

interface TaskStreamViewerProps {
  task: TaskInfo;
  /**
   * Completed stream text from task.output.text — when provided and the task
   * is not running, rendered directly without opening a Centrifugo subscription.
   */
  completedStream?: string;
  /** Completed token count (for the badge). */
  tokenCount?: number;
}

/**
 * On-demand streaming viewer for a single perf-token task.
 *
 * When the task is already completed with stored output, the completed view is
 * rendered immediately.  When running, a Show / Hide toggle controls an
 * on-demand Centrifugo subscription so that the WebSocket connection is only
 * open while the user is actively watching the stream.
 */
export function TaskStreamViewer({ task, completedStream, tokenCount }: TaskStreamViewerProps) {
  const [open, setOpen] = useState(false);
  const [jsonViewEnabled, setJsonViewEnabled] = useState(false);
  const isRunning = task.status === "running";

  // Subscribe only while the panel is open AND the task is still running.
  const { streamText, tokenCount: liveCount, phase } = useTaskStream(
    task.thread_id,
    open && isRunning,
  );

  // Task completed with stored output — static completed view, no subscription.
  if (!isRunning && completedStream) {
    const hasOutput = task.output != null && Object.keys(task.output).length > 0;
    return (
      <div>
        <StreamingOutput
          stream={completedStream}
          isRunning={false}
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
        {jsonViewEnabled && hasOutput && (
          <div style={{ marginTop: 8 }}>
            <JsonOutput data={task.output} />
          </div>
        )}
      </div>
    );
  }

  const displayCount = open && liveCount > 0 ? liveCount : tokenCount;

  return (
    <div>
      <Button
        size="small"
        type={open ? "primary" : "default"}
        onClick={() => {
          const newOpen = !open;
          setOpen(newOpen);
          if (newOpen && isRunning) {
            enableTaskStream(task.thread_id, task.task_id).catch((err) => {
              console.error(
                "[TaskStreamViewer] enableTaskStream failed task_id=%s thread_id=%s",
                task.task_id, task.thread_id, err,
              );
            });
          }
        }}
        disabled={!isRunning}
        style={{ marginBottom: open ? 6 : 0 }}
      >
        {open ? "Hide" : "Show Stream"}
      </Button>

      {open && (
        phase === "connecting" ? (
          <Flex align="center" gap={6} style={{ marginTop: 6 }}>
            <LoadingOutlined style={{ fontSize: 11 }} />
            <Text type="secondary" style={{ fontSize: 12, fontStyle: "italic" }}>
              Awaiting streaming…
            </Text>
          </Flex>
        ) : (
          <div>
            <StreamingOutput
              stream={streamText}
              isRunning={phase === "streaming"}
              tokenCount={displayCount}
              lifecycleLabel={phase === "done" || phase === "error" ? "Completed" : "Streaming…"}
            />
            {(phase === "done" || phase === "error") && streamText.length > 0 && (
              <Flex align="center" gap={6} style={{ marginTop: 6 }}>
                <Switch
                  size="small"
                  checked={jsonViewEnabled}
                  onChange={setJsonViewEnabled}
                />
                <Text type="secondary" style={{ fontSize: 11 }}>JSON View</Text>
              </Flex>
            )}
            {jsonViewEnabled && (phase === "done" || phase === "error") &&
              task.output != null && Object.keys(task.output).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <JsonOutput data={task.output} />
              </div>
            )}
          </div>
        )
      )}
    </div>
  );
}
