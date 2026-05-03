import { useEffect, useRef } from "react";
import { Flex, Tag, Typography, theme } from "antd";
import { CheckCircleOutlined, LoadingOutlined } from "@ant-design/icons";

const { Text, Paragraph } = Typography;

/**
 * LLM streaming output with lifecycle status and token count.
 *
 * Shows a "Streaming…" spinner while tokens are arriving, transitions to
 * "Completed" with a check icon when done.  Optionally shows the token count.
 */
export function StreamingOutput({
  stream,
  isRunning,
  tokenCount,
  lifecycleLabel,
}: {
  stream: string;
  isRunning: boolean;
  /** Total tokens received — displayed as a count badge in the header. */
  tokenCount?: number;
  /** Override the lifecycle label (e.g. "Ingesting", "Digesting"). Defaults to "Streaming…" / "Completed". */
  lifecycleLabel?: string;
}) {
  const { token } = theme.useToken();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isRunning) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [stream, isRunning]);

  const label = lifecycleLabel ?? (isRunning ? "Streaming…" : "Completed");

  return (
    <div
      style={{
        background: token.colorFillQuaternary,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        padding: "8px 12px",
      }}
    >
      {/* Lifecycle header — always visible */}
      <Flex align="center" gap={6} style={{ marginBottom: 8 }}>
        {isRunning ? (
          <LoadingOutlined style={{ color: token.colorPrimary, fontSize: 11 }} />
        ) : (
          <CheckCircleOutlined style={{ color: token.colorSuccess, fontSize: 11 }} />
        )}
        <Text type="secondary" style={{ fontSize: 11, fontStyle: "italic" }}>
          {label}
        </Text>
        {tokenCount !== undefined && tokenCount > 0 && (
          <Tag
            color={isRunning ? "processing" : "success"}
            style={{ fontSize: 10, padding: "0 4px", lineHeight: "16px", marginLeft: 2 }}
          >
            {tokenCount.toLocaleString()} tokens
          </Tag>
        )}
      </Flex>
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
