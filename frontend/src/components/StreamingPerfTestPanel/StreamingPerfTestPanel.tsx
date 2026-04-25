import { useMemo, useCallback, useEffect, useRef, useState } from "react";
import { Button, Col, Divider, Dropdown, Form, InputNumber, Row, Segmented, Space, Statistic, Table, Tag, Typography, theme } from "antd";
import { CheckCircleOutlined, DownOutlined, PauseCircleOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { useSessionManager } from "./useSessionManager";
import { buildColumns } from "./columns";
import { StreamTaskDrawer } from "./StreamTaskDrawer";
import { AggregateStatsHeader } from "./AggregateStatsHeader";
import { useStyles } from "./StreamingPerfTestPanel.styles";
import type { PerfTestConfig, ThreadSession } from "./types";
import type { TaskTypeMeta } from "../../types";
import { DEFAULT_PERF_CONFIG } from "./types";

const { Title } = Typography;

export interface StreamingPerfTestPanelProps {
  /** Guest user token for submitting stream requests. */
  userToken: string;
  /** Task type metadata for rendering the StreamTaskDrawer. */
  taskMeta?: TaskTypeMeta | null;
  /** Called when the user clicks Complete — signals App to mark the top node as completed. */
  onComplete?: () => void;
}

export function StreamingPerfTestPanel({
  userToken,
  taskMeta = null,
  onComplete,
}: StreamingPerfTestPanelProps) {
  const { token } = theme.useToken();
  const styles = useStyles();
  const [config, setConfig] = useState<PerfTestConfig>(DEFAULT_PERF_CONFIG);
  const [addCount, setAddCount] = useState<number>(2);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [customAddVal, setCustomAddVal] = useState<number | null>(null);
  const [customAddError, setCustomAddError] = useState<string>("");
  const [taskDrawerThreadId, setTaskDrawerThreadId] = useState<string | null>(null);
  /** thread_id of the session whose streaming token log is currently visible.
   *  At most one session may be expanded at a time. */
  const [expandedTokenLogId, setExpandedTokenLogId] = useState<string | null>(null);

  const handleToggleTokenLog = useCallback((thread_id: string) => {
    setExpandedTokenLogId((prev) => (prev === thread_id ? null : thread_id));
  }, []);

  /** Measured height of the sticky control-panel header — used as offsetHeader for the Table. */
  const stickyHeaderRef = useRef<HTMLDivElement>(null);
  const [stickyHeaderH, setStickyHeaderH] = useState(0);
  useEffect(() => {
    const el = stickyHeaderRef.current;
    if (!el) return;
    const obs = new ResizeObserver(() => setStickyHeaderH(el.offsetHeight));
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Presets differ by mode: Concurrency tests need 10× more streams.
  const ADD_PRESETS = config.testMode === "concurrency"
    ? [10, 20, 50, 100, 200, 500]
    : [1, 2, 5, 10, 20, 50, 100];

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
    frozen,
    handleAddRequest,
    handleRestart,
    handleComplete,
    handleCancelAll,
    handleCancelOne,
  } = useSessionManager(userToken, config);

  // Single global toggle: controls are locked while any stream is running.
  const isActive = activeCount > 0;

  const columns = useMemo(
    () => buildColumns(handleCancelOne, config.tokenCount, frozen, setTaskDrawerThreadId, config.testMode, config.timeoutSecs, token, config.tokenPerSec, expandedTokenLogId, handleToggleTokenLog),
    [handleCancelOne, config.tokenCount, config.testMode, config.timeoutSecs, config.tokenPerSec, frozen, token, expandedTokenLogId, handleToggleTokenLog],
  );

  return (
    <div style={styles.outerContainer}>
      {/* ── Sticky header pane (title + buttons + config + stats) ── */}
      <div style={styles.stickyHeader} ref={stickyHeaderRef}>
        {/* Title row + action buttons */}
        <div style={styles.titleRow}>
          <div style={styles.titleLeft}>
            <SyncOutlined spin={isActive} />
            <Title level={5} style={{ margin: 0 }}>Performance Test</Title>
            {isActive && <Tag color="blue">{activeCount} active</Tag>}
          </div>
          <div style={styles.titleRight}>
            <Dropdown.Button
              type="primary"
              disabled={isActive}
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
                <div style={styles.dropdownContent}>
                  {menu}
                  <Divider style={styles.dropdownDivider} />
                  <Space direction="vertical" size={4} style={styles.dropdownCustomArea}>
                    <Space>
                      <InputNumber
                        size="small"
                        min={1}
                        placeholder="Custom…"
                        value={customAddVal}
                        status={customAddError ? "error" : ""}
                        onChange={(v) => { setCustomAddVal(v); setCustomAddError(""); }}
                        onPressEnter={handleCustomSet}
                        style={styles.customInputNumber}
                      />
                      <Button size="small" type="primary" onClick={handleCustomSet}>Set</Button>
                    </Space>
                    {customAddError && (
                      <Typography.Text type="danger" style={styles.errorText}>{customAddError}</Typography.Text>
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
              disabled={isActive}
            >
              Restart
            </Button>
            <Button
              icon={<CheckCircleOutlined />}
              onClick={() => { handleComplete(); onComplete?.(); }}
              disabled={sessions.length === 0 || isActive}
            >
              Complete
            </Button>
            <Button
              danger
              icon={<PauseCircleOutlined />}
              onClick={handleCancelAll}
              disabled={!isActive}
            >
              Cancel All
            </Button>
          </div>
        </div>

        {/* Config inputs */}
        <Form layout="inline" style={styles.configForm}>
          <Form.Item label="Test Mode">
            <Segmented
              options={[
                { label: "Throughput", value: "throughput" },
                { label: "Concurrency", value: "concurrency" },
              ]}
              value={config.testMode}
              disabled={isActive}
              onChange={(v) => {
                setConfig((c) => ({ ...c, testMode: v as "throughput" | "concurrency" }));
                // Reset addCount to mode-appropriate default.
                setAddCount(v === "concurrency" ? 10 : 2);
              }}
            />
          </Form.Item>
          {config.testMode === "throughput" ? (
            <Form.Item label="Tokens / request">
              <InputNumber
                min={1000}
                max={1_000_000}
                step={10_000}
                value={config.tokenCount}
                disabled={isActive}
                formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
                parser={(v) => parseInt((v ?? "").replace(/,/g, ""), 10) as unknown as 100000}
                onChange={(v) => v !== null && setConfig((c) => ({ ...c, tokenCount: v }))}
                style={styles.tokenInputNumber}
              />
            </Form.Item>
          ) : (
            <Form.Item label="Tokens / sec">
              <InputNumber
                min={100}
                max={100_000}
                step={100}
                value={config.tokenPerSec}
                disabled={isActive}
                formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
                parser={(v) => parseInt((v ?? "").replace(/,/g, ""), 10) as unknown as 500}
                onChange={(v) => v !== null && setConfig((c) => ({ ...c, tokenPerSec: v }))}
                style={styles.tpsInputNumber}
              />
            </Form.Item>
          )}
          <Form.Item label="Timeout (s)">
            <InputNumber
              min={10}
              max={3600}
              step={10}
              value={config.timeoutSecs}
              disabled={isActive}
              addonAfter="s"
              onChange={(v) => v !== null && setConfig((c) => ({ ...c, timeoutSecs: v }))}
              style={styles.timeoutInputNumber}
            />
          </Form.Item>
        </Form>

        {/* Live stats */}
        <Row gutter={12}>
          <Col span={8}><Statistic title="Total Tokens" value={totalTokens} /></Col>
          <Col span={8}><Statistic title="Active Streams" value={activeCount} /></Col>
          <Col span={8}><Statistic title="Completed" value={completedCount} /></Col>
        </Row>
        <AggregateStatsHeader sessions={sessions} />
      </div>

      {/* ── Scrollable grid ── */}
      <div style={styles.tableSection}>
        <Table<ThreadSession>
          rowKey="thread_id"
          columns={columns}
          dataSource={sessions}
          pagination={false}
          size="small"
          bordered
          sticky={{ offsetHeader: stickyHeaderH }}
        />
      </div>

      <StreamTaskDrawer
        threadId={taskDrawerThreadId}
        taskMeta={taskMeta}
        onClose={() => setTaskDrawerThreadId(null)}
      />
    </div>
  );
}
