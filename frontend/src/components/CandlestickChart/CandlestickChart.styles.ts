import type { CSSProperties } from "react";
import { FONT_XS, FONT_SM } from "../../styles/shared";

/** Static styles for CandlestickChart component. */
export const styles: Record<string, CSSProperties> = {
  noDataText: FONT_SM,
  symbolText: FONT_SM,
  currencyTag: { ...FONT_XS, margin: 0 },
  metaText: FONT_XS,
  chartContainer: { width: "100%" },
  indicatorLabel: { ...FONT_XS, flexShrink: 0 },
  indicatorSelect: { flex: 1, minWidth: 200 },
  panelIndicatorKey: FONT_XS,
  panelIndicatorMissing: FONT_XS,
};
