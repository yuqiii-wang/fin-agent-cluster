import { theme } from "antd";
import type { CSSProperties } from "react";

/** Token-based styles for ReportDrawerPanel component. */
export function useStyles(): Record<string, CSSProperties> {
  const { token } = theme.useToken();
  return {
    searchBar: { width: "100%", marginBottom: 20 },
    inputUppercase: { textTransform: "uppercase" },
    loadingCenter: { textAlign: "center", padding: "40px 0" },
    errorText: { color: token.colorError, padding: "8px 0" },
  };
}
