import { useCallback, useState } from "react";
import { Button, Drawer, Input, Space, Spin, theme } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { ReportView } from "../components/ReportView";
import { fetchLatestReport } from "../api";
import type { StrategyReport } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ReportDrawerPanel({ open, onClose }: Props) {
  const { token } = theme.useToken();
  const [reportSymbol, setReportSymbol] = useState("");
  const [reportData, setReportData] = useState<StrategyReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const handleLoadReport = useCallback(async () => {
    const sym = reportSymbol.trim().toUpperCase();
    if (!sym) return;
    setReportLoading(true);
    setReportError(null);
    setReportData(null);
    try {
      const data = await fetchLatestReport(sym);
      setReportData(data);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : String(err));
    } finally {
      setReportLoading(false);
    }
  }, [reportSymbol]);

  return (
    <Drawer
      title="Strategy Report"
      placement="right"
      width="75vw"
      open={open}
      onClose={onClose}
      styles={{ body: { padding: "16px 12px", overflowY: "auto" } }}
    >
      <Space.Compact style={{ width: "100%", marginBottom: 20 }}>
        <Input
          placeholder="Enter ticker symbol, e.g. AAPL"
          value={reportSymbol}
          onChange={(e) => setReportSymbol(e.target.value)}
          onPressEnter={handleLoadReport}
          style={{ textTransform: "uppercase" }}
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          onClick={handleLoadReport}
          loading={reportLoading}
        >
          Load
        </Button>
      </Space.Compact>

      {reportLoading && (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <Spin size="large" />
        </div>
      )}

      {reportError && !reportLoading && (
        <div style={{ color: token.colorError, padding: "8px 0" }}>
          {reportError}
        </div>
      )}

      {reportData && !reportLoading && (
        <ReportView report={reportData} />
      )}
    </Drawer>
  );
}
