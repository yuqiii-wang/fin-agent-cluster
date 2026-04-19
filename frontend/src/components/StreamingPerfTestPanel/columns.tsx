import { Badge, Button, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { InfoCircleOutlined, PauseCircleOutlined } from "@ant-design/icons";
import type { ThreadSession } from "./types";

const { Text } = Typography;

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
        const map: Record<ThreadSession["status"], { color: string; label: string }> = {
          connecting: { color: "blue",       label: "Connecting" },
          running:    { color: "processing", label: "Running"    },
          completed:  { color: "success",    label: "Completed"  },
          failed:     { color: "error",      label: "Failed"     },
          cancelled:  { color: "warning",    label: "Cancelled"  },
          stopped:    { color: "default",    label: "Stopped"    },
        };
        const { color, label } = map[status] ?? { color: "default", label: status };
        const badge = (
          <Badge
            status={color as "processing" | "success" | "error" | "warning" | "default"}
            text={<Tag color={color === "processing" ? "blue" : color}>{label}</Tag>}
          />
        );
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
        // Start from pub_start_ms (set when ingest completes); fall back to
        // start_ms before ingest is done so the column is never blank.
        const startMs = record.pub_start_ms ?? record.start_ms;
        // Use Date.now() while active so the per-second tick drives updates;
        // freeze at last_token_ms once the session is closed by SSE signal.
        const endMs = record.closed ? record.last_token_ms : Date.now();
        const secs = Math.max(0, Math.floor((endMs - startMs) / 1000));
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        return record.pub_start_ms == null
          ? <Text type="secondary">—</Text>
          : (m > 0 ? `${m}m ${s}s` : `${s}s`);
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
