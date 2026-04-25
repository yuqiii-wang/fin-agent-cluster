import { theme } from "antd";
import type { CSSProperties } from "react";

interface ReportViewStyles {
  container: CSSProperties;
  header: CSSProperties;
  riskIcon: CSSProperties;
  growthIcon: CSSProperties;
  anomalyIcon: CSSProperties;
}

export function useStyles(): ReportViewStyles {
  const { token } = theme.useToken();
  return {
    container: { maxWidth: 1100, margin: "0 auto", padding: "16px 8px" },
    header: {
      marginBottom: 20,
      paddingBottom: 12,
      borderBottom: `1px solid ${token.colorBorder}`,
    },
    riskIcon: { color: token.colorError },
    growthIcon: { color: token.colorSuccess },
    anomalyIcon: { color: token.colorWarning },
  };
}
