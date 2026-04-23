import { Badge, Button, Space, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { InfoCircleOutlined, PauseCircleOutlined, UnorderedListOutlined } from "@ant-design/icons";
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
  handleCancelOne: (thread_id: string) => void,
  totalTokensPerStream: number = 100_000,
  frozen: boolean = false,
  onTasksClick?: (thread_id: string) => void,
  testMode: "throughput" | "concurrency" = "throughput",
  timeoutSecs: number = 60,
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
      title: "Mode",
      key: "test_mode",
      width: 110,
      align: "center",
      render: (_: unknown, record: ThreadSession) => (
        record.test_mode === "concurrency"
          ? <Tag color="cyan">Concurrency</Tag>
          : <Tag color="blue">Throughput</Tag>
      ),
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
          digesting:  { badgeStatus: "processing", tagColor: "blue",       label: "Digesting"   },
          running:    { badgeStatus: "processing", tagColor: "blue",       label: "Running"     },
          completed:  { badgeStatus: "success",    tagColor: "success",    label: "Completed"   },
          failed:     { badgeStatus: "error",      tagColor: "error",      label: "Failed"      },
          cancelled:  { badgeStatus: "warning",    tagColor: "warning",    label: "Cancelled"   },

          timeout:    { badgeStatus: "warning",    tagColor: "volcano",    label: "Timeout"     },
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
          <Tooltip title="Token writes to the Redis perf stream. Throughput: produced/total with write rate. Concurrency: continuous write alongside digest until timeout.">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      key: "ingest",
      width: 160,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        const { ingest_status, ingest_produced, ingest_total, ingest_tps } = record;
        const rowMode = record.test_mode;
        if (!ingest_status && ingest_produced === undefined) return <Text type="secondary">—</Text>;
        const produced = ingest_produced ?? 0;
        // total_tokens=0 from backend means concurrency mode (no fixed total).
        const total = (ingest_total && ingest_total > 0) ? ingest_total : null;
        const tpsLabel = ingest_tps != null ? ` @ ${ingest_tps.toLocaleString()} tps` : "";
        const label = total
          ? `${produced.toLocaleString()} / ${total.toLocaleString()}${tpsLabel}`
          : `${produced.toLocaleString()}${tpsLabel}`;
        if (ingest_status === "running") {
          const pctText = total
            ? `${((produced / total) * 100).toFixed(1)}% ingested${tpsLabel}`
            : rowMode === "concurrency"
              ? `continuous ingest${tpsLabel}`
              : `ingesting${tpsLabel}`;
          return (
            <Tooltip title={pctText}>
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
          // In concurrency mode timeout is the expected end state — show success.
          const badgeStatus = rowMode === "concurrency" ? "success" : "warning";
          const tooltipText = rowMode === "concurrency" ? "Ingest ended (timeout — expected)" : "Ingest timed out";
          return (
            <Tooltip title={tooltipText}>
              <Badge status={badgeStatus} text={<Text style={{ fontSize: 11 }}>{label}</Text>} />
            </Tooltip>
          );
        }
        return <Text style={{ fontSize: 11 }}>{label}</Text>;
      },
    },
    {
      title: "Concurrent",
      key: "concurrent",
      width: 160,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        const { concurrent_batch_size, concurrent_digest_tps, concurrent_ingest_tps, concurrent_stream_len } = record;
        if (concurrent_batch_size == null) return <Text type="secondary">—</Text>;
        const digestTps = concurrent_digest_tps ?? 0;
        const ingestTps = concurrent_ingest_tps ?? 0;
        const ratio = ingestTps > 0 ? (digestTps / ingestTps).toFixed(1) : "∞";
        const backlog = concurrent_stream_len != null ? concurrent_stream_len.toLocaleString() : "?";
        return (
          <Tooltip title={`digest/ingest ratio: ${ratio}×  |  backlog: ${backlog} tokens`}>
            <Text style={{ fontSize: 11 }}>
              batch: <strong>{concurrent_batch_size}</strong>
            </Text>
          </Tooltip>
        );
      },
    },
    {
      title: (
        <span>
          Progress{" "}
          <Tooltip title="Throughput: tokens received / target. Concurrency: elapsed time since first token / timeout (per stream).">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      key: "progress",
      width: 100,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        if (record.test_mode === "concurrency") {
          const refMs = record.digest_start_ms;
          if (refMs == null) return <Text type="secondary">—</Text>;
          const endMs = record.closed ? record.last_token_ms : Date.now();
          const elapsedMs = Math.max(0, endMs - refMs);
          const pct = Math.min((elapsedMs / (timeoutSecs * 1000)) * 100, 100);
          return (
            <Tooltip title={`${(elapsedMs / 1000).toFixed(1)}s / ${timeoutSecs}s`}>
              <span>{pct.toFixed(1)}%</span>
            </Tooltip>
          );
        }
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
        const digestStart = record.digest_start_ms ?? record.pub_start_ms ?? record.start_ms;
        // In concurrency mode there is no fixed total; sessions end via timeout (record.closed).
        const allConsumedRate = record.test_mode === "throughput" && record.tokens >= totalTokensPerStream;
        const endMs = (record.closed || allConsumedRate) ? record.last_token_ms : Date.now();
        const elapsed = (endMs - digestStart) / 1000;
        const rate = elapsed > 0 ? (record.tokens / elapsed) : 0;
        const usingFallback = record.digest_start_ms == null;
        const tooltipText = usingFallback
          ? `Using ${record.pub_start_ms != null ? "pub_start_ms" : "start_ms"} as digest start (first token batch not yet received)`
          : `digest_start_ms: first perf_token_batch timestamp | elapsed: ${elapsed.toFixed(2)}s`;
        return (
          <Tooltip title={tooltipText}>
            <span style={usingFallback ? { color: "#faad14" } : undefined}>
              {rate > 0 ? rate.toFixed(1) : "0.0"}
            </span>
          </Tooltip>
        );
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
        const startMs = record.digest_start_ms ?? record.pub_start_ms;
        if (startMs == null) return <Text type="secondary">—</Text>;
        const allConsumed = record.test_mode === "throughput" && record.tokens >= totalTokensPerStream;
        const endMs = (record.closed || allConsumed) ? record.last_token_ms : Date.now();
        const elapsedMs = Math.max(0, endMs - startMs);
        return fmtDuration(elapsedMs);
      },
    },
    {
      title: (
        <span>
          TPS / sec{" "}
          <Tooltip title="Per-second token throughput during the digest (streaming) phase. Each bar represents one second; height is proportional to peak TPS in this row.">
            <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
          </Tooltip>
        </span>
      ),
      key: "tps_chart",
      width: 180,
      render: (_: unknown, record: ThreadSession) => {
        const BAR_W = 3;
        const BAR_GAP = 1;
        const CHART_H = 28;
        const MAX_BARS = 50;

        const history = record.tps_history ?? [];
        if (history.length === 0) return <Text type="secondary">—</Text>;
        const bars = history.slice(-MAX_BARS);

        const maxTps = Math.max(...bars, 1);
        const chartW = bars.length * (BAR_W + BAR_GAP);
        const lastTps = bars[bars.length - 1];
        const tooltipText = `Last: ${lastTps.toLocaleString()} tps  |  Peak: ${maxTps.toLocaleString()} tps  |  ${bars.length}s`;
        return (
          <Tooltip title={tooltipText}>
            <svg
              width={chartW}
              height={CHART_H}
              style={{ display: "block", overflow: "visible" }}
            >
              {bars.map((tps, i) => {
                const h = Math.max(1, Math.round((tps / maxTps) * CHART_H));
                const isLast = i === bars.length - 1;
                return (
                  <rect
                    key={i}
                    x={i * (BAR_W + BAR_GAP)}
                    y={CHART_H - h}
                    width={BAR_W}
                    height={h}
                    fill={isLast ? "#1677ff" : "#91caff"}
                  />
                );
              })}
            </svg>
          </Tooltip>
        );
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
      width: 160,
      render: (_: unknown, record: ThreadSession) => (
        <Space size={4} wrap>
          {onTasksClick && (
            <Button
              size="small"
              icon={<UnorderedListOutlined />}
              onClick={() => onTasksClick(record.thread_id)}
            >
              Tasks
            </Button>
          )}
          {!record.closed && !frozen && (
            <Button
              size="small"
              danger
              icon={<PauseCircleOutlined />}
              onClick={() => handleCancelOne(record.thread_id)}
            >
              Cancel
            </Button>
          )}
        </Space>
      ),
    },
  ];
}
