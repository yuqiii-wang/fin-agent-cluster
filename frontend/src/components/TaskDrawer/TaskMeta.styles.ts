import type { CSSProperties } from "react";
import { FONT_XS } from "../../styles/shared";

/** Styles for TaskMeta component. */
export const styles: Record<string, CSSProperties> = {
  threadFlex: { minWidth: 0 },
  threadCode: {
    ...FONT_XS,
    maxWidth: 200,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    display: "inline-block",
  },
  copyIcon: { fontSize: 10, cursor: "pointer", flexShrink: 0 },
  codeText: FONT_XS,
};
