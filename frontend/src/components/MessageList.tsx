import { useEffect, useRef } from "react";
import { Flex, Typography, theme } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { NodeList } from "./NodeList";
import { ReportView } from "./ReportView";
import type { ChatMessage, NodeGroup } from "../types";

const { Text } = Typography;

interface Props {
  messages: ChatMessage[];
  onNodeClick: (node: NodeGroup) => void;
}

export function MessageList({ messages, onNodeClick }: Props) {
  const { token } = theme.useToken();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <Flex
      vertical
      gap={16}
      style={{
        flex: 1,
        overflowY: "auto",
        padding: "16px 20px",
      }}
    >
      {messages.map((msg) => (
        <Flex
          key={msg.id}
          justify={msg.role === "user" ? "flex-end" : "flex-start"}
        >
          <div
            style={{
              maxWidth: msg.role === "assistant" ? "85%" : "72%",
              background: msg.role === "user" ? token.colorPrimary : token.colorBgContainer,
              border: msg.role === "assistant" ? `1px solid ${token.colorBorder}` : "none",
              borderRadius: token.borderRadiusLG,
              padding: "10px 14px",
              color: token.colorText,
            }}
          >
            {msg.role === "assistant" ? (
              <>
                {/* 1. Node pipeline — appears as soon as any node starts */}
                {msg.nodes && msg.nodes.length > 0 && (
                  <NodeList nodes={msg.nodes} threadId={msg.thread_id ?? ""} onNodeClick={onNodeClick} />
                )}

                {/* 2. Report viewer — replaces raw text once DB insert completes */}
                {msg.report ? (
                  <div style={{ marginTop: msg.nodes?.length ? 12 : 0 }}>
                    <ReportView report={msg.report} />
                  </div>
                ) : msg.text ? (
                  <div
                    style={{
                      fontSize: 14,
                      lineHeight: 1.75,
                      color: token.colorText,
                      marginTop: msg.nodes?.length ? 12 : 0,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {msg.text}
                    {msg.streamingCursor && (
                      <span className="blink-cursor" />
                    )}
                  </div>
                ) : msg.status === "running" && msg.nodes && msg.nodes.length > 0 && msg.nodes.every((n) => n.status === "completed") ? (
                  /* All nodes done — waiting for final summary text */
                  <Flex
                    align="center"
                    gap={8}
                    style={{
                      marginTop: 8,
                      color: token.colorTextSecondary,
                      fontSize: 13,
                    }}
                  >
                    <LoadingOutlined />
                    <span>Preparing summary…</span>
                  </Flex>
                ) : msg.status === "running" && (!msg.nodes || msg.nodes.length === 0) ? (
                  /* Placeholder while waiting for first node / first token */
                  <Flex
                    align="center"
                    gap={8}
                    style={{
                      marginTop: 0,
                      color: token.colorTextSecondary,
                      fontSize: 13,
                    }}
                  >
                    <LoadingOutlined />
                    <span>Processing…</span>
                  </Flex>
                ) : null}
              </>
            ) : (
              <Text style={{ color: "#fff", fontSize: 14 }}>{msg.text}</Text>
            )}
          </div>
        </Flex>
      ))}
      <div ref={bottomRef} />
    </Flex>
  );
}
