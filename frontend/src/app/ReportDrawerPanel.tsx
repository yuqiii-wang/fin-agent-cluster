import { useCallback, useState } from "react";
import { Button, Drawer, Input, Space, Spin } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { ReportView } from "../components/ReportView";
import { fetchLatestReport } from "../api";
import type { StrategyReport } from "../types";
import { useStyles } from "./ReportDrawerPanel.styles";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ReportDrawerPanel({ open, onClose }: Props) {
  const styles = useStyles();
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
      <Space.Compact style={styles.searchBar}>
        <Input
          placeholder="Enter ticker symbol, e.g. AAPL"
          value={reportSymbol}
          onChange={(e) => setReportSymbol(e.target.value)}
          onPressEnter={handleLoadReport}
          style={styles.inputUppercase}
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
        <div style={styles.loadingCenter}>
          <Spin size="large" />
        </div>
      )}

      {reportError && !reportLoading && (
        <div style={styles.errorText}>
          {reportError}
        </div>
      )}

      {reportData && !reportLoading && (
        <ReportView report={reportData} />
      )}
    </Drawer>
  );
}
