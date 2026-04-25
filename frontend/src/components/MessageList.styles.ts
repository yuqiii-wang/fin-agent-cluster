import { theme } from "antd";
import type { CSSProperties } from "react";

/** Token-based styles for MessageList component. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    list: {
      flex: 1,
      overflowY: "auto",
      padding: "16px 20px",
    },
    assistantBubble: {
      maxWidth: "85%",
      background: token.colorBgContainer,
      border: `1px solid ${token.colorBorder}`,
      borderRadius: token.borderRadiusLG,
      padding: "10px 14px",
      color: token.colorText,
    },
    userBubble: {
      maxWidth: "72%",
      background: token.colorPrimary,
      borderRadius: token.borderRadiusLG,
      padding: "10px 14px",
    },
    messageText: {
      fontSize: 14,
      lineHeight: 1.75,
      color: token.colorText,
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
    },
    loadingState: {
      color: token.colorTextSecondary,
      fontSize: 13,
    },
    userText: { color: token.colorTextLightSolid, fontSize: 14 },
    reportWrapper: { marginTop: 12 },
  };
}
