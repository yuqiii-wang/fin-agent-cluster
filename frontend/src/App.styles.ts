import { theme } from "antd";
import type { CSSProperties } from "react";
import { FLEX_COL, FLEX_ROW_CENTER } from "./styles/shared";

/** Token-based styles for App root layout. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    layout: {
      height: "100vh",
      background: token.colorBgLayout,
      ...FLEX_COL,
    },
    header: {
      ...FLEX_ROW_CENTER,
      background: token.colorBgContainer,
      borderBottom: `1px solid ${token.colorBorder}`,
      padding: "0 20px",
      justifyContent: "space-between",
    },
    headerLeft: { ...FLEX_ROW_CENTER, gap: 12 },
    title: { color: token.colorText, margin: 0 },
    tag: { margin: 0 },
    content: { ...FLEX_COL, flex: 1, overflow: "hidden" },
    perfOuter: { ...FLEX_COL, flex: 1, overflow: "hidden" },
    perfTopSection: { flex: "0 0 auto" },
    perfScrollSection: { flex: 1, overflowY: "auto", padding: "0 20px 16px" },
    footer: { padding: 0, background: "transparent" },
    footerExit: { padding: "8px 20px", display: "flex", justifyContent: "flex-end" },
  };
}
