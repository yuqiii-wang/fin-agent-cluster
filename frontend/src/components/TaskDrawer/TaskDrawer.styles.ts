import type { CSSProperties } from "react";
import { FONT_XS } from "../../styles/shared";

/** Styles for TaskDrawer component. */
export const styles: Record<string, CSSProperties> = {
  collapse: { background: "transparent", border: "none" },
  collapseItem: { marginBottom: 6, borderRadius: 6 },
  sectionLabel: { ...FONT_XS, fontWeight: 500 },
  timeText: FONT_XS,
  clockIcon: { marginRight: 4 },
};
