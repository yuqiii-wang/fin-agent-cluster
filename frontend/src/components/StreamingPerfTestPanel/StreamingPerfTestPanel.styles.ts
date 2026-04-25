import { theme } from "antd";
import type { CSSProperties } from "react";
import { FLEX_ROW_CENTER } from "../../styles/shared";

/** Token-based styles for StreamingPerfTestPanel component. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    outerContainer: { width: "100%" },
    stickyHeader: {
      position: "sticky",
      top: 0,
      zIndex: 20,
      background: token.colorBgContainer,
      borderBottom: `1px solid ${token.colorBorderSecondary}`,
      padding: "12px 16px 10px",
    },
    titleRow: { ...FLEX_ROW_CENTER, justifyContent: "space-between", marginBottom: 10 },
    titleLeft: { ...FLEX_ROW_CENTER, gap: 8 },
    titleRight: { display: "flex", gap: 8 },
    dropdownContent: {
      background: token.colorBgElevated,
      borderRadius: token.borderRadiusLG,
      boxShadow: token.boxShadowSecondary,
    },
    dropdownDivider: { margin: "4px 0" },
    dropdownCustomArea: { padding: "4px 12px 8px", width: "100%" },
    configForm: { marginBottom: 10 },
    customInputNumber: { width: 90 },
    tokenInputNumber: { width: 130 },
    tpsInputNumber: { width: 120 },
    timeoutInputNumber: { width: 100 },
    errorText: { fontSize: 12 },
    tableSection: { padding: "12px 16px 16px" },
  };
}
