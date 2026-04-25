import { theme } from "antd";
import type { CSSProperties } from "react";
import { FONT_SM } from "../../styles/shared";

interface OutlookGridStyles {
  riseText: CSSProperties;
  fallText: CSSProperties;
  riseIcon: CSSProperties;
  fallIcon: CSSProperties;
  riseCardHeader: Record<string, CSSProperties>;
  fallCardHeader: Record<string, CSSProperties>;
  item: CSSProperties;
  itemLabel: CSSProperties;
}

export function useStyles(): OutlookGridStyles {
  const { token } = theme.useToken();
  return {
    riseText: { fontSize: 14, color: token.colorSuccess },
    fallText: { fontSize: 14, color: token.colorError },
    riseIcon: { color: token.colorSuccess },
    fallIcon: { color: token.colorError },
    riseCardHeader: { header: { background: token.colorSuccessBg }, body: { padding: "10px 14px" } },
    fallCardHeader: { header: { background: token.colorErrorBg }, body: { padding: "10px 14px" } },
    item: { marginBottom: 10 },
    itemLabel: FONT_SM,
  };
}
