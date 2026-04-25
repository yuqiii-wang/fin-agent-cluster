import type { CSSProperties } from "react";

/** Styles for TaskLabel component. */
export const styles: Record<string, CSSProperties> = {
  container: { width: "100%", minWidth: 0 },
  labelText: { fontSize: 13, flex: 1, minWidth: 0 },
  statusTag: { marginRight: 0, flexShrink: 0 },
};
