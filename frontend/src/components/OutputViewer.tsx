/**
 * OutputViewer — smart output renderer for agent task/node output fields.
 *
 * Routing logic:
 *  1. LLM streaming (stream tokens present) → ThinkingStream
 *  2. Task failed                            → ErrorDisplay
 *  3. Task running (LLM, no tokens yet)      → LlmWaitingStatus
 *  4. Task running (non-LLM)                 → RunningDescription (task_key label)
 *  5. Completed output with bars array       → CandlestickChart (data-driven)
 *  6. Any other completed output             → JsonViewer
 *  7. No output                              → "No output available"
 */

import { useEffect, useRef, useState } from "react";
import { Flex, Typography, theme } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo, TaskTypeMeta } from "../types";
import { JsonViewer } from "./JsonViewer";
import { CandlestickChart, type OHLCVBar } from "./CandlestickChart";

const { Text, Paragraph } = Typography;

// ─── LLM provider display names ───────────────────────────────────────────────
const PROVIDER_LABELS: Record<string, string> = {
  ark: "Doubao/ARK",
  gemini: "Gemini",
  ollama: "Ollama (local)",
};

function providerLabel(provider?: string): string {
  if (!provider) return "LLM";
  return PROVIDER_LABELS[provider] ?? provider;
}

// ─── Task type helpers ─────────────────────────────────────────────────────────

export function isLlmTask(taskKey: string, meta: TaskTypeMeta): boolean {
  return meta.llm_task_keys.includes(taskKey);
}

/** Human-readable running description derived directly from the task key. */
function taskRunningLabel(taskKey: string): string {
  return taskKey.replace(/_/g, " ") + "…";
}

// ─── Sub-renderers ─────────────────────────────────────────────────────────────

/** LLM streaming output with a "thinking" indicator while tokens are arriving. */
function ThinkingStream({
  stream,
  isRunning,
}: {
  stream: string;
  isRunning: boolean;
}) {
  const { token } = theme.useToken();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as tokens arrive
  useEffect(() => {
    if (isRunning) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [stream, isRunning]);

  return (
    <div
      style={{
        background: token.colorFillQuaternary,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        padding: "8px 12px",
      }}
    >
      {isRunning && (
        <Flex align="center" gap={6} style={{ marginBottom: 8 }}>
          <LoadingOutlined style={{ color: token.colorPrimary, fontSize: 11 }} />
          <Text type="secondary" style={{ fontSize: 11, fontStyle: "italic" }}>
            Thinking…
          </Text>
        </Flex>
      )}
      <Paragraph
        style={{
          fontSize: 12,
          fontFamily: "'Courier New', monospace",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          maxHeight: 340,
          overflowY: "auto",
          margin: 0,
          lineHeight: 1.6,
        }}
      >
        {stream}
        {isRunning && <span className="blink-cursor" />}
      </Paragraph>
      <div ref={bottomRef} />
    </div>
  );
}

/** Staged status display while LLM has not sent any tokens yet. */
function LlmWaitingStatus({ provider }: { provider?: string }) {
  const label = providerLabel(provider);
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 1500);
    const t2 = setTimeout(() => setPhase(2), 5000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);

  const messages = [
    `Connecting to ${label}…`,
    `Awaiting response from ${label}…`,
    `Still waiting for ${label} — model may be slow…`,
  ];

  return (
    <Flex align="center" gap={6}>
      <LoadingOutlined style={{ fontSize: 11 }} />
      <Text type="secondary" style={{ fontSize: 12, fontStyle: "italic" }}>
        {messages[phase]}
      </Text>
    </Flex>
  );
}

/** Generic running description for non-LLM tasks. */
function RunningDescription({ taskKey }: { taskKey: string }) {
  return (
    <Flex align="center" gap={6}>
      <LoadingOutlined style={{ fontSize: 11 }} />
      <Text type="secondary" style={{ fontSize: 12, fontStyle: "italic" }}>
        {taskRunningLabel(taskKey)}
      </Text>
    </Flex>
  );
}

/** Error display for failed tasks. */
function ErrorDisplay({ error }: { error?: unknown }) {
  const { token } = theme.useToken();
  return (
    <Paragraph
      style={{
        background: token.colorErrorBg,
        border: `1px solid ${token.colorErrorBorder}`,
        borderRadius: token.borderRadius,
        padding: "8px 12px",
        fontSize: 12,
        fontFamily: "'Courier New', monospace",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        color: token.colorError,
        margin: 0,
      }}
    >
      {error != null ? String(error) : "Task failed with no error details."}
    </Paragraph>
  );
}

// ─── OutputViewer ──────────────────────────────────────────────────────────────

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
  // ── Error state (always takes precedence) ────────────────────────────────────
  if (task.status === "failed") {
    return <ErrorDisplay error={task.output?.error} />;
  }

  const isLlm = taskMeta ? isLlmTask(task.task_key, taskMeta) : false;

  // ── LLM stream tokens present → thinking-style rendering ─────────────────────
  if (stream) {
    return (
      <ThinkingStream stream={stream} isRunning={task.status === "running"} />
    );
  }

  // ── Running state (no stream yet) ────────────────────────────────────────────
  if (task.status === "running") {
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

  // ── Completed output with candlestick matrix → CandlestickChart ───────────────
  if (task.output?.chart_type === "candlestick") {
    const dates = task.output.dates as string[] | undefined;
    const matrix = task.output.ohlcv as number[][] | undefined;
    if (dates?.length && matrix?.length) {
      const bars: OHLCVBar[] = dates.map((date, i) => ({
        date,
        open: matrix[i][0],
        high: matrix[i][1],
        low: matrix[i][2],
        close: matrix[i][3],
        volume: matrix[i][4],
      }));
      // task.output.symbol is the ticker; task.output.source is the data provider.
      const sym = typeof task.output.symbol === "string" ? task.output.symbol : "";
      return (
        <CandlestickChart
          bars={bars}
          symbol={sym}
          taskKey={task.task_key}
        />
      );
    }
  }

  // ── Default: JSON viewer ──────────────────────────────────────────────────────
  return <JsonViewer data={task.output} maxHeight={400} />;
}
