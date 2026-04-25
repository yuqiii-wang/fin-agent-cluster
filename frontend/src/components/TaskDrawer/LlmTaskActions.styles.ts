import type { CSSProperties } from "react";
import { FONT_XS } from "../../styles/shared";

/** Styles for LlmTaskActions component. */
export const styles: Record<string, CSSProperties> = {
  tooltipContent: { maxWidth: 220 },
  tooltipParagraph: { margin: 0 },
  button: FONT_XS,
  loadingIcon: FONT_XS,
};
