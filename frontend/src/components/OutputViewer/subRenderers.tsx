import { useEffect, useRef, useState } from "react";
import { Flex, Typography, theme } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { providerLabel, taskRunningLabel } from "./helpers";

const { Text, Paragraph } = Typography;

/** LLM streaming output with a "thinking" indicator while tokens are arriving. */
export function ThinkingStream({
  stream,
  isRunning,
}: {
  stream: string;
  isRunning: boolean;
}) {
  const { token } = theme.useToken();
  const bottomRef = useRef<HTMLDivElement>(null);

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
export function LlmWaitingStatus({ provider }: { provider?: string }) {
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
export function RunningDescription({ taskKey }: { taskKey: string }) {
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
export function ErrorDisplay({ error }: { error?: unknown }) {
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
