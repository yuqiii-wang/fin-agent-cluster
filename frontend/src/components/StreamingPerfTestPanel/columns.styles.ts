import type { CSSProperties } from "react";
import { FONT_XS, MONO_XS } from "../../styles/shared";

/** Static column cell styles for StreamingPerfTestPanel columns. */
export const styles: Record<string, CSSProperties> = {
  smallText: FONT_XS,
  monoSmallText: MONO_XS,
  svgBlock: { display: "block", overflow: "visible" },
};

/** Inline styles that depend on runtime values (antd token colors are passed from parent). */
export function getColumnColors(token: {
  colorPrimary: string;
  colorPrimaryBorder: string;
  colorWarning: string;
  colorTextTertiary: string;
}) {
  return {
    infoIcon: { color: token.colorTextTertiary, cursor: "help" } as CSSProperties,
    fallbackText: { color: token.colorWarning } as CSSProperties,
    svgBarActive: token.colorPrimary,
    svgBarInactive: token.colorPrimaryBorder,
    /** Dashed reference line drawn at the target token rate in concurrency mode. */
    svgTargetLine: token.colorTextTertiary,
  };
}
