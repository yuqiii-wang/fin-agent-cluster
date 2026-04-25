import { theme } from "antd";
import type { CSSProperties } from "react";
import { FLEX_COL, FONT_SM, FONT_XS, MONO_FONT_FAMILY } from "../styles/shared";

/** Token-based styles for NodeList component. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    steps: { marginTop: 8 },
    loadingCenter: { marginTop: 8 },
    streamingContainer: { ...FLEX_COL, marginTop: 8 },
    streamingLabel: { ...FONT_XS, color: token.colorPrimary },
    streamingIcon: { fontSize: 10, color: token.colorPrimary },
    streamingText: {
      fontFamily: MONO_FONT_FAMILY,
      ...FONT_SM,
      maxHeight: 200,
      overflow: "auto",
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
      background: token.colorFillTertiary,
      padding: "6px 8px",
      borderRadius: token.borderRadius,
    },
    cursorOpacity: { opacity: 0.4 },
    waitingContainer: { marginTop: 8 },
    waitingText: { ...FONT_SM, fontStyle: "italic" },
    ioContainer: { marginTop: 8 },
    labelText: { ...FONT_XS, fontWeight: 600 },
    stepTitle: FONT_SM,
    stepDesc: FONT_XS,
    runningIcon: { fontSize: 10, marginRight: 4 },
    streamingRunningIcon: { fontSize: 10, marginRight: 4, color: token.colorPrimary },
    streamingColorText: { color: token.colorPrimary },
    cancelledIcon: { color: token.colorWarning },
  };
}
