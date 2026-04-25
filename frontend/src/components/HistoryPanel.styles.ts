import { theme } from "antd";
import type { CSSProperties } from "react";
import { FLEX_ROW_CENTER, FONT_SM } from "../styles/shared";

/** Token-based styles for HistoryPanel component. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    emptyState: {
      textAlign: "center",
      padding: "40px 16px",
      color: token.colorTextSecondary,
    },
    listItem: { padding: "10px 16px", cursor: "pointer" },
    titleRow: { ...FLEX_ROW_CENTER, gap: 8 },
    titleText: { maxWidth: 230, display: "inline-block" },
    titleTag: { flexShrink: 0 },
    timeText: FONT_SM,
  };
}
