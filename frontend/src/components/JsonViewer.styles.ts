import { theme } from "antd";
import type { CSSProperties } from "react";

/** Token-based styles for JsonViewer component. */
export function useStyles() {
  const { token } = theme.useToken();
  return {
    container: { position: "relative" } as CSSProperties,
    copyButton: {
      position: "absolute",
      top: 4,
      right: 4,
      zIndex: 1,
      padding: "0 4px",
      height: 18,
    } as CSSProperties,
    viewer: {
      fontFamily: "'Courier New', monospace",
      fontSize: 11,
      background: token.colorBgLayout,
      border: `1px solid ${token.colorBorder}`,
      borderRadius: token.borderRadius,
      padding: "6px 10px",
      marginTop: 2,
      overflow: "auto",
    } as CSSProperties,
    toggleArrow: {
      cursor: "pointer",
      userSelect: "none",
      fontSize: 10,
      marginRight: 2,
      display: "inline-block",
      width: 10,
      color: token.colorTextTertiary,
    } as CSSProperties,
    copyIconSuccess: { color: token.colorSuccess, fontSize: 10 } as CSSProperties,
    copyIconDefault: { fontSize: 10 } as CSSProperties,
    /** Syntax-highlighting color palette derived from antd tokens. */
    colors: {
      key: token.colorPrimary,
      string: token.colorSuccessText,
      number: token.colorWarningText,
      boolean: "#722ed1",
      null: token.colorTextDisabled,
      bracket: token.colorText,
      summary: token.colorTextTertiary,
    },
  };
}
