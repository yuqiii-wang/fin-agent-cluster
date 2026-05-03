import { memo, useEffect, useRef } from "react";
import { Flex, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { NodeList } from "./NodeList";
import type { ChatMessage, NodeGroup } from "../types";
import { useStyles } from "./MessageList.styles";

const { Text } = Typography;

interface Props {
  messages: ChatMessage[];
  onNodeClick: (node: NodeGroup) => void;
}

export const MessageList = memo(function MessageList({ messages, onNodeClick }: Props) {
  const styles = useStyles();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <Flex
      vertical
      gap={16}
      style={styles.list}
    >
      {messages.map((msg) => (
        <Flex
          key={msg.id}
          justify={msg.role === "user" ? "flex-end" : "flex-start"}
        >
          <div
            style={
              msg.role === "assistant"
                ? styles.assistantBubble
                : styles.userBubble
            }
          >
            {msg.role === "assistant" ? (
              <>
                {/* 1. Node pipeline — appears as soon as any node starts */}
                {msg.nodes && msg.nodes.length > 0 && (
                  <NodeList
                    nodes={msg.nodes}
                    threadId={msg.thread_id ?? ""}
                    onNodeClick={onNodeClick}
                    queryRunning={msg.status === "running"}
                    queryResumable={msg.status === "cancelled" || msg.status === "failed" || msg.status === "paused"}
                  />
                )}

                {msg.text ? (
                  <div
                    style={{
                      ...styles.messageText,
                      marginTop: msg.nodes?.length ? 12 : 0,
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
                      ...styles.loadingState,
                      marginTop: 8,
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
                      ...styles.loadingState,
                      marginTop: 0,
                    }}
                  >
                    <LoadingOutlined />
                    <span>Processing…</span>
                  </Flex>
                ) : null}
              </>
            ) : (
              <Text style={styles.userText}>{msg.text}</Text>
            )}
          </div>
        </Flex>
      ))}
      <div ref={bottomRef} />
    </Flex>
  );
});
