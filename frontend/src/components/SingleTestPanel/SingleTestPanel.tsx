/**
 * SingleTestPanel — sends one mock-single query and visualizes the graph execution.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────┐
 *   │  [Send request]   [Reset]    status tag      │  ← controls
 *   │  thread_id: xxx                              │  ← session info (after send)
 *   ├─────────────────────────────────────────────┤
 *   │  GraphVisualizationPanel                    │  ← shows after first node arrives
 *   └─────────────────────────────────────────────┘
 */

import { useEffect, useState } from "react";
import { Button, Space, Tag, Typography, theme, Alert, Spin } from "antd";
import { ReloadOutlined, SendOutlined } from "@ant-design/icons";
import { useSingleTestSession } from "../../services/singleTest";
import { GraphVisualizationPanel } from "../GraphVisualizationPanel";
import { fetchSystemHealth, type SystemHealthResponse } from "../../api/queries";

const { Text } = Typography;

export interface SingleTestPanelProps {
  userToken: string;
}

export function SingleTestPanel({ userToken }: SingleTestPanelProps) {
  const { token } = theme.useToken();
  const { session, graphState, tokenStreams, tokenCounts, sendRequest, resumeRequest, reset, isActive, isPendingControl } = useSingleTestSession(userToken);
  const anyPending = isActive || isPendingControl;
  const [systemHealth, setSystemHealth] = useState<SystemHealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [hasAutoRun, setHasAutoRun] = useState(false);

  // Fetch system health on mount
  useEffect(() => {
    async function checkHealth() {
      try {
        setHealthLoading(true);
        const health = await fetchSystemHealth();
        setSystemHealth(health);
        setHealthError(null);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setHealthError(msg);
      } finally {
        setHealthLoading(false);
      }
    }
    checkHealth();
  }, []);

  // Auto-run after health check completes and 1 sec delay
  useEffect(() => {
    if (healthLoading || hasAutoRun || session) return;

    const timer = setTimeout(() => {
      sendRequest();
      setHasAutoRun(true);
    }, 1000);

    return () => clearTimeout(timer);
  }, [healthLoading, hasAutoRun, session, sendRequest]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "16px 24px" }}>
      {/* Controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          paddingBottom: 16,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          marginBottom: 20,
        }}
      >
        <Button
          type="primary"
          icon={<SendOutlined />}
          loading={session?.status === "submitting"}
          disabled={anyPending}
          onClick={sendRequest}
        >
          Send request
        </Button>

        <Button
          icon={<ReloadOutlined />}
          onClick={reset}
          disabled={anyPending}
        >
          Reset
        </Button>

        {/* Status tag */}
        {session?.status === "submitting" && <Tag color="processing">Submitting…</Tag>}
        {session?.status === "streaming" && <Tag color="blue">Streaming</Tag>}
        {isPendingControl && <Spin size="small" />}
        {session?.status === "done" && (
          <Tag color={session.doneStatus === "completed" ? "success" : "warning"}>
            {session.doneStatus ?? "Done"}
          </Tag>
        )}
        {session?.status === "error" && <Tag color="error">Error</Tag>}

        {/* System health status */}
        {healthLoading && <Spin size="small" />}
        {healthError && <Tag color="error">Health check failed</Tag>}
        {systemHealth && !healthLoading && !healthError && (
          <Tag color={systemHealth.all_healthy ? "success" : "warning"}>
            {systemHealth.all_healthy ? "All healthy" : "Unhealthy"} ({systemHealth.healthy_count}/{systemHealth.total})
          </Tag>
        )}

        {/* Thread ID */}
        {session?.thread_id && (
          <Text type="secondary" style={{ fontSize: 12, fontFamily: "monospace" }}>
            {session.thread_id}
          </Text>
        )}
      </div>

      {/* Error state */}
      {session?.status === "error" && (
        <Alert
          type="error"
          message="Request failed"
          description={session.error}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Graph visualization — shown once nodes start arriving */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        <GraphVisualizationPanel
          graphState={graphState}
          threadId={session?.thread_id}
          tokenStreams={tokenStreams}
          tokenCounts={tokenCounts}
          onResume={resumeRequest}
          isPendingControl={isPendingControl}
        />
      </div>
    </div>
  );
}
