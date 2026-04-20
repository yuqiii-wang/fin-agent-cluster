import { useMemo, useState } from "react";
import { Button, Col, Divider, Dropdown, Form, InputNumber, Row, Segmented, Space, Statistic, Table, Tag, Typography, theme } from "antd";
import { CheckCircleOutlined, DownOutlined, PauseCircleOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { useSessionManager } from "./useSessionManager";
import { buildColumns } from "./columns";
import type { PerfTestConfig, ThreadSession } from "./types";
import { DEFAULT_PERF_CONFIG } from "./types";

const { Title } = Typography;

export interface StreamingPerfTestPanelProps {
  /** Initial thread_id from the first submitted query. */
  initialThreadId: string;
  /** Guest user token for submitting additional requests. */
  userToken: string;
  /** Called when the user clicks Complete — signals App to mark the top node as completed. */
  onComplete?: () => void;
}

export function StreamingPerfTestPanel({
  initialThreadId,
  userToken,
  onComplete,
}: StreamingPerfTestPanelProps) {
  const { token } = theme.useToken();
  const [config, setConfig] = useState<PerfTestConfig>(DEFAULT_PERF_CONFIG);
  const [addCount, setAddCount] = useState<number>(2);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [customAddVal, setCustomAddVal] = useState<number | null>(null);
  const [customAddError, setCustomAddError] = useState<string>("");

  const ADD_PRESETS = [1, 2, 5, 10, 20, 50, 100];

  const handlePresetSelect = ({ key }: { key: string }) => {
    setAddCount(Number(key));
    setDropdownOpen(false);
    setCustomAddError("");
  };

  const handleCustomSet = () => {
    if (customAddVal === null) return;
    if (customAddVal > 1000) {
      setCustomAddError("Max 1,000 requests");
      return;
    }
    if (customAddVal < 1) {
      setCustomAddError("Min 1 request");
      return;
    }
    setAddCount(customAddVal);
    setCustomAddVal(null);
    setCustomAddError("");
    setDropdownOpen(false);
  };

  const {
    sessions,
    totalTokens,
    activeCount,
    completedCount,
    avgTokenRate,
    perSecStats,
    frozen,
    handleAddRequest,
    handleRestart,
    handleComplete,
    handleStopAll,
    handleStopOne,
  } = useSessionManager(initialThreadId, userToken, config);

  const columns = useMemo(() => buildColumns(handleStopOne, config.tokenCount, frozen), [handleStopOne, config.tokenCount, frozen]);

  return (
    <div style={{ width: "100%" }}>
      {/* ── Sticky header pane (title + buttons + config + stats) ── */}
      <div style={{
        position: "sticky",
        top: 0,
        zIndex: 20,
        background: token.colorBgContainer,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        padding: "12px 16px 10px",
      }}>
        {/* Title row + action buttons */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <SyncOutlined spin={activeCount > 0} />
            <Title level={5} style={{ margin: 0 }}>Performance Test</Title>
            {activeCount > 0 && <Tag color="blue">{activeCount} active</Tag>}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Dropdown.Button
              type="primary"
              disabled={frozen}
              open={dropdownOpen}
              onOpenChange={(open) => { setDropdownOpen(open); if (!open) setCustomAddError(""); }}
              onClick={() => handleAddRequest(addCount)}
              icon={<DownOutlined />}
              menu={{
                items: ADD_PRESETS.map((n) => ({ key: String(n), label: String(n) })),
                selectedKeys: [String(addCount)],
                onClick: handlePresetSelect,
              }}
              dropdownRender={(menu) => (
                <div style={{ background: token.colorBgElevated, borderRadius: token.borderRadiusLG, boxShadow: token.boxShadowSecondary }}>
                  {menu}
                  <Divider style={{ margin: "4px 0" }} />
                  <Space direction="vertical" size={4} style={{ padding: "4px 12px 8px", width: "100%" }}>
                    <Space>
                      <InputNumber
                        size="small"
                        min={1}
                        placeholder="Custom…"
                        value={customAddVal}
                        status={customAddError ? "error" : ""}
                        onChange={(v) => { setCustomAddVal(v); setCustomAddError(""); }}
                        onPressEnter={handleCustomSet}
                        style={{ width: 90 }}
                      />
                      <Button size="small" type="primary" onClick={handleCustomSet}>Set</Button>
                    </Space>
                    {customAddError && (
                      <Typography.Text type="danger" style={{ fontSize: 12 }}>{customAddError}</Typography.Text>
                    )}
                  </Space>
                </div>
              )}
            >
              Add {addCount} request{addCount !== 1 ? "s" : ""}
            </Dropdown.Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={handleRestart}
              disabled={frozen || activeCount > 0}
            >
              Restart
            </Button>
            <Button
              icon={<CheckCircleOutlined />}
              onClick={() => { handleComplete(); onComplete?.(); }}
              disabled={frozen || sessions.length === 0 || activeCount > 0}
            >
              Complete
            </Button>
            <Button
              danger
              icon={<PauseCircleOutlined />}
              onClick={handleStopAll}
              disabled={frozen || activeCount === 0}
            >
              Stop All
            </Button>
          </div>
        </div>

        {/* Config inputs */}
        <Form layout="inline" style={{ marginBottom: 10 }}>
          <Form.Item label="Tokens / request">
            <InputNumber
              min={1000}
              max={1_000_000}
              step={10_000}
              value={config.tokenCount}
              disabled={activeCount > 0 || frozen}
              formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
              parser={(v) => parseInt((v ?? "").replace(/,/g, ""), 10) as unknown as 100000}
              onChange={(v) => v !== null && setConfig((c) => ({ ...c, tokenCount: v }))}
              style={{ width: 130 }}
            />
          </Form.Item>
          <Form.Item label="Timeout (s)">
            <InputNumber
              min={10}
              max={3600}
              step={10}
              value={config.timeoutSecs}
              disabled={activeCount > 0 || frozen}
              addonAfter="s"
              onChange={(v) => v !== null && setConfig((c) => ({ ...c, timeoutSecs: v }))}
              style={{ width: 100 }}
            />
          </Form.Item>
          <Form.Item label="Pub mode">
            <Segmented
              options={[
                { label: "Browser", value: "browser" },
                { label: "Locust", value: "locust" },
              ]}
              value={config.pubMode}
              disabled={activeCount > 0 || frozen}
              onChange={(v) => setConfig((c) => ({ ...c, pubMode: v as "browser" | "locust" }))}
            />
          </Form.Item>
        </Form>

        {/* Live stats */}
        <Row gutter={16}>
          <Col span={4}><Statistic title="Total Tokens" value={totalTokens} /></Col>
          <Col span={4}><Statistic title="Active Streams" value={activeCount} /></Col>
          <Col span={4}><Statistic title="Completed" value={completedCount} /></Col>
          <Col span={4}><Statistic title="Avg Token Rate" value={avgTokenRate.toFixed(1)} suffix="tps" /></Col>
          <Col span={4}><Statistic title="Tokens/sec" value={perSecStats.tps} suffix="tps" /></Col>
          <Col span={4}><Statistic title="Peak tps" value={perSecStats.peak} suffix="tps" /></Col>
        </Row>
      </div>

      {/* ── Scrollable grid ── */}
      <div style={{ padding: "12px 16px 16px" }}>
        <Table<ThreadSession>
          rowKey="thread_id"
          columns={columns}
          dataSource={sessions}
          pagination={false}
          size="small"
          bordered
        />
      </div>
    </div>
  );
}
