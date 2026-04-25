import { theme } from "antd";
import type { CSSProperties } from "react";

/** Token-based styles for ChatInput component. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    inputBar: {
      padding: "12px 16px",
      background: token.colorBgContainer,
      borderTop: `1px solid ${token.colorBorder}`,
    },
  };
}
