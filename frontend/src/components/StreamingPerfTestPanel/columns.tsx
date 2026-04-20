import { Badge, Button, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { InfoCircleOutlined, PauseCircleOutlined } from "@ant-design/icons";
import type { ThreadSession } from "./types";

const { Text } = Typography;

/** Format a duration in milliseconds for display.
 *  < 1 ms  → "1ms"  (minimum resolution)
 *  < 1 s   → "Xms"
 *  < 60 s  → "X.Xs"
 *  ≥ 60 s  → "Xm Xs"
 */
function fmtDuration(ms: number): string {
  if (ms < 1) return "1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSecs = ms / 1000;
  if (totalSecs < 60) return `${totalSecs.toFixed(1)}s`;
  const m = Math.floor(totalSecs / 60);
  const s = Math.floor(totalSecs % 60);
  return `${m}m ${s}s`;
}

export function buildColumns(
  handleStopOne: (thread_id: string) => void,
  totalTokensPerStream: number = 100_000,
  frozen: boolean = false,
): ColumnsType<ThreadSession> {
  return [
    {
      title: "Stream",
      dataIndex: "label",
      key: "label",
      width: 100,
      render: (label: string) => <Text strong>{label}</Text>,
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (status: ThreadSession["status"], record: ThreadSession) => {
        type BadgeStatus = "processing" | "success" | "error" | "warning" | "default";
        const map: Record<ThreadSession["status"], { badgeStatus: BadgeStatus; tagColor: string; label: string }> = {          connecting: { badgeStatus: "default",    tagColor: "default",    label: "Connecting"  },
          received:   { badgeStatus: "default",    tagColor: "cyan",       label: "Received"    },
          preparing:  { badgeStatus: "processing", tagColor: "geekblue",   label: "Preparing"   },
          ingesting:  { badgeStatus: "processing", tagColor: "purple",     label: "Ingesting"   },
          sending:    { badgeStatus: "processing", tagColor: "blue",       label: "Sending"     },
          running:    { badgeStatus: "processing", tagColor: "blue",       label: "Running"     },
          completed:  { badgeStatus: "success",    tagColor: "success",    label: "Completed"   },
          failed:     { badgeStatus: "error",      tagColor: "error",      label: "Failed"      },
          cancelled:  { badgeStatus: "warning",    tagColor: "warning",    label: "Cancelled"   },
          stopped:    { badgeStatus: "default",    tagColor: "default",    label: "Stopped"     },
        };
        const { tagColor, label } = map[status] ?? { badgeStatus: "default", tagColor: "default", label: status };
        const badge = <Tag color={tagColor}>{label}</Tag>;
        if (status === "failed" && record.error) {
          return (
            <Tooltip title={record.error} color="red">
              {badge}
            </Tooltip>
          );
        }
        return badge;
      },
    },
    {
      title: (
        <span>
          Pub Mode{" "}
          <Tooltip title="Browser: tokens streamed live to the UI. Locust: tokens consumed silently; only aggregate metrics are reported.">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      dataIndex: "pub_mode",
      key: "pub_mode",
      width: 90,
      render: (mode: ThreadSession["pub_mode"]) => (
        <Tag color={mode === "locust" ? "green" : "cyan"} style={{ fontSize: 11 }}>
          {mode === "locust" ? "Locust" : "Browser"}
        </Tag>
      ),
    },
    {
      title: "Tokens",
      dataIndex: "tokens",
      key: "tokens",
      width: 90,
      align: "right",
      render: (tokens: number) => tokens.toLocaleString(),
    },
    {
      title: (
        <span>
          Ingest{" "}
          <Tooltip title="Tokens bulk-written to the Redis perf stream during the ingest phase. Shows produced/total and per-second write rate.">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      key: "ingest",
      width: 160,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        const { ingest_status, ingest_produced, ingest_total, ingest_tps } = record;
        if (!ingest_status && ingest_produced === undefined) return <Text type="secondary">—</Text>;
        const produced = ingest_produced ?? 0;
        const total = ingest_total ?? totalTokensPerStream;
        const pct = Math.min((produced / total) * 100, 100);
        const tpsLabel = ingest_tps != null ? ` @ ${ingest_tps.toLocaleString()} tps` : "";
        const label = `${produced.toLocaleString()} / ${total.toLocaleString()}${tpsLabel}`;
        if (ingest_status === "running") {
          return (
            <Tooltip title={`${pct.toFixed(1)}% ingested${tpsLabel}`}>
              <Badge status="processing" text={<Text style={{ fontSize: 11 }}>{label}</Text>} />
            </Tooltip>
          );
        }
        if (ingest_status === "completed") {
          return (
            <Tooltip title="Ingest complete">
              <Badge status="success" text={<Text style={{ fontSize: 11 }}>{produced.toLocaleString()}</Text>} />
            </Tooltip>
          );
        }
        if (ingest_status === "timeout") {
          return (
            <Tooltip title="Ingest timed out">
              <Badge status="warning" text={<Text style={{ fontSize: 11 }}>{label}</Text>} />
            </Tooltip>
          );
        }
        return <Text style={{ fontSize: 11 }}>{label}</Text>;
      },
    },
    {
      title: (
        <span>
          Ingest Time{" "}
          <Tooltip title="Backend wall-clock time for the ingest phase (token write to Redis stream). Sourced from the authoritative perf_ingest_complete SSE event.">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      key: "ingest_time",
      width: 110,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        if (record.ingest_ms == null) return <Text type="secondary">—</Text>;
        return fmtDuration(record.ingest_ms);
      },
    },
    {
      title: "Progress",
      key: "progress",
      width: 100,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        const pct = Math.min((record.tokens / totalTokensPerStream) * 100, 100);
        return `${pct.toFixed(1)}%`;
      },
    },
    {
      title: "Token Rate (tps)",
      key: "rate",
      width: 130,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        // Locust mode: backend reports the authoritative digest tps directly.
        if (record.digest_tps != null) return record.digest_tps.toLocaleString();
        const endMs = (record.tokens > 0 || record.closed) ? record.last_token_ms : Date.now();
        const elapsed = (endMs - record.start_ms) / 1000;
        return elapsed > 0 ? (record.tokens / elapsed).toFixed(1) : "0.0";
      },
    },
    {
      title: (
        <span>
          Digest Time{" "}
          <Tooltip title="Time spent streaming tokens to the client (pub phase only — ingest phase excluded).">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      key: "duration",
      width: 120,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        // Locust mode: use the authoritative backend-reported digest_ms.
        if (record.digest_ms != null) return fmtDuration(record.digest_ms);
        // Browser mode: compute from client-side timestamps.
        // pub_start_ms is set when ingest completes; absent until then.
        if (record.pub_start_ms == null) return <Text type="secondary">—</Text>;
        const allConsumed = record.tokens >= totalTokensPerStream;
        const endMs = (record.closed || allConsumed) ? record.last_token_ms : Date.now();
        const elapsedMs = Math.max(0, endMs - record.pub_start_ms);
        return fmtDuration(elapsedMs);
      },
    },
    {
      title: "Thread ID",
      dataIndex: "thread_id",
      key: "thread_id",
      ellipsis: true,
      render: (tid: string) => (
        <Tooltip title={tid}>
          <Text type="secondary" style={{ fontFamily: "monospace", fontSize: 11 }}>
            {tid.slice(0, 8)}…
          </Text>
        </Tooltip>
      ),
    },
    {
      title: "Last Received Token",
      key: "last_token",
      ellipsis: true,
      render: (_: unknown, record: ThreadSession) => (
        <Text
          type="secondary"
          style={{ fontFamily: "monospace", fontSize: 11 }}
          ellipsis={{ tooltip: record.last_token_text }}
        >
          {record.last_token_text || "—"}
        </Text>
      ),
    },
    {
      title: "Action",
      key: "action",
      width: 80,
      render: (_: unknown, record: ThreadSession) =>
        !record.closed && !frozen ? (
          <Button
            size="small"
            danger
            icon={<PauseCircleOutlined />}
            onClick={() => handleStopOne(record.thread_id)}
          >
            Stop
          </Button>
        ) : null,
    },
  ];
}
