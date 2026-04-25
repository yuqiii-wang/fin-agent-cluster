import { Badge, Button, Space, Tag, Tooltip, Typography } from "antd";
import type { GlobalToken } from "antd/es/theme/interface";
import type { ColumnsType } from "antd/es/table";
import { InfoCircleOutlined, PauseCircleOutlined, UnorderedListOutlined } from "@ant-design/icons";
import type { ThreadSession } from "./types";
import { TERMINAL_STATUSES } from "./types";
import { isSessionStable } from "./useSessionManager";
import { styles, getColumnColors } from "./columns.styles";
import { ThinkingStream } from "../OutputViewer/subRenderers";

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
  token?: GlobalToken,
  tokenPerSec: number = 500,
  expandedTokenLogId?: string | null,
  onToggleTokenLog?: (thread_id: string) => void,
): ColumnsType<ThreadSession> {
  const colors = token ? getColumnColors(token) : getColumnColors({
    colorPrimary: "#1677ff",
    colorPrimaryBorder: "#91caff",
    colorWarning: "#faad14",
    colorTextTertiary: "#8c8c8c",
  });
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
            <InfoCircleOutlined style={colors.infoIcon} />
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
          // In concurrency mode the ingest runs alongside streaming for the full
          // test duration — show a green (success) dot since this is the expected
          // healthy state, not a transient "working" indicator.
          const badgeStatus = rowMode === "concurrency" ? "success" as const : "processing" as const;
          return (
            <Tooltip title={pctText}>
              <Badge status={badgeStatus} text={<Text style={styles.smallText}>{label}</Text>} />
            </Tooltip>
          );
        }
        if (ingest_status === "completed") {
          return (
            <Tooltip title="Ingest complete">
              <Badge status="success" text={<Text style={styles.smallText}>{produced.toLocaleString()}</Text>} />
            </Tooltip>
          );
        }
        if (ingest_status === "timeout") {
          // In concurrency mode timeout is the expected end state — show success.
          const badgeStatus = rowMode === "concurrency" ? "success" : "warning";
          const tooltipText = rowMode === "concurrency" ? "Ingest ended (timeout — expected)" : "Ingest timed out";
          return (
            <Tooltip title={tooltipText}>
              <Badge status={badgeStatus} text={<Text style={styles.smallText}>{label}</Text>} />
            </Tooltip>
          );
        }
        return <Text style={styles.smallText}>{label}</Text>;
      },
    },
    {
      title: (
        <span>
          Read Batch{" "}
          <Tooltip title="Token count per SSE read batch from the browser consumer. Displayed as: 1st / max / ave / last. 1st = first batch received; max = largest single batch; ave = mean across all batches; last = most recent batch.">
            <InfoCircleOutlined style={colors.infoIcon} />
          </Tooltip>
        </span>
      ),
      key: "concurrent",
      width: 180,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        const { concurrent_batch_size, concurrent_digest_tps, concurrent_ingest_tps, concurrent_stream_len } = record;
        const { batch_first, batch_max, batch_ave, batch_last } = record;
        const hasBatchStats = batch_first !== undefined;
        const hasConcurrent = concurrent_batch_size != null;
        if (!hasBatchStats && !hasConcurrent) return <Text type="secondary">—</Text>;
        const concurrentLabel = hasConcurrent ? (() => {
          const digestTps = concurrent_digest_tps ?? 0;
          const ingestTps = concurrent_ingest_tps ?? 0;
          const ratio = ingestTps > 0 ? (digestTps / ingestTps).toFixed(1) : "∞";
          const backlog = concurrent_stream_len != null ? concurrent_stream_len.toLocaleString() : "?";
          return (
            <Tooltip title={`adaptive batch | digest/ingest ratio: ${ratio}×  |  backlog: ${backlog} tokens`}>
              <Text style={styles.smallText}>
                cur: <strong>{concurrent_batch_size}</strong>
              </Text>
            </Tooltip>
          );
        })() : null;
        return (
          <Space direction="vertical" size={0} style={{ textAlign: "right" }}>
            {hasBatchStats && (
              <Tooltip title="1st / max / ave / last token count per read batch">
                <Text style={styles.smallText}>
                  {batch_first}
                  {" / "}
                  <strong>{batch_max}</strong>
                  {" / "}
                  {batch_ave}
                  {" / "}
                  {batch_last}
                </Text>
              </Tooltip>
            )}
            {concurrentLabel}
          </Space>
        );
      },
    },
    {
      title: (
        <span>
          Progress{" "}
          <Tooltip title={`Throughput: tokens received / target. Concurrency: elapsed time since first token / timeout (per stream). Stable = ≥20% of prior buckets (excl. last 2s) exceeded 90% of the ${tokenPerSec} tps target — backend then concludes the stream as completed.`}>
            <InfoCircleOutlined style={colors.infoIcon} />
          </Tooltip>
        </span>
      ),
      key: "progress",
      width: 120,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        if (record.test_mode === "concurrency") {
          const refMs = record.digest_start_ms;
          if (refMs == null) return <Text type="secondary">—</Text>;
          const isFrozen = record.closed || TERMINAL_STATUSES.has(record.status);
          const endMs = isFrozen ? record.last_token_ms : Date.now();
          const elapsedMs = Math.max(0, endMs - refMs);
          const pct = Math.min((elapsedMs / (timeoutSecs * 1000)) * 100, 100);
          const stable = isSessionStable(record.tps_history ?? [], tokenPerSec);
          return (
              <Tooltip title={`${(elapsedMs / 1000).toFixed(1)}s / ${timeoutSecs}s${stable ? ` — TPS stable: ≥20% of prior history buckets (excl. last 2s) exceeded 90% of the ${tokenPerSec} tps target. Backend is concluding the stream as completed.` : ""}`}>
              <span>
                {pct.toFixed(1)}%
                {stable && (
                  <Tag color="green" style={{ marginLeft: 4, fontSize: 10, padding: "0 4px" }}>stable</Tag>
                )}
              </span>
            </Tooltip>
          );
        }
        // "completed" status means the backend confirmed all published tokens
        // were received. Show 100% regardless of record.tokens vs totalTokensPerStream.
        if (record.status === "completed" && record.tokens >= totalTokensPerStream) {
          return "100.0%";
        }
        const pct = Math.min((record.tokens / totalTokensPerStream) * 100, 100);
        if (pct >= 100) return "100.0%";
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
        const isFrozenRate = record.closed || allConsumedRate || TERMINAL_STATUSES.has(record.status);
        const endMs = isFrozenRate ? record.last_token_ms : Date.now();
        const elapsed = (endMs - digestStart) / 1000;
        const rate = elapsed > 0 ? (record.tokens / elapsed) : 0;
        const usingFallback = record.digest_start_ms == null;
        const tooltipText = usingFallback
          ? `Using ${record.pub_start_ms != null ? "pub_start_ms" : "start_ms"} as digest start (first token batch not yet received)`
          : `digest_start_ms: first perf_token_batch timestamp | elapsed: ${elapsed.toFixed(2)}s`;
        return (
          <Tooltip title={tooltipText}>
            <span style={usingFallback ? colors.fallbackText : undefined}>
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
            <InfoCircleOutlined style={colors.infoIcon} />
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
        const isFrozenDuration = record.closed || allConsumed || TERMINAL_STATUSES.has(record.status);
        const endMs = isFrozenDuration ? record.last_token_ms : Date.now();
        const elapsedMs = Math.max(0, endMs - startMs);
        return fmtDuration(elapsedMs);
      },
    },
    {
      title: (
        <span>
          TPS / sec{" "}
          <Tooltip title="Per-second token throughput during the digest (streaming) phase. Each bar represents one second; height is proportional to peak TPS in this row.">
            <InfoCircleOutlined style={colors.infoIcon} />
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
        // Each bar = one raw 1-second TPS bucket; no smoothing.
        const bars = history.slice(-MAX_BARS);

        // ── Scale ─────────────────────────────────────────────────────────────
        // In concurrency mode use a fixed scale anchored at 1.5× the target rate
        // so stable-period bars appear at a consistent ~67 % height regardless of
        // end-of-stream flush spikes.  In throughput mode keep the dynamic scale.
        const isConcurrency = testMode === "concurrency" && tokenPerSec > 0;
        const normBase = isConcurrency
          ? tokenPerSec * 1.5
          : Math.max(...bars, 1);

        // Dashed target-rate reference line Y (concurrency mode).
        const targetLineY = isConcurrency
          ? CHART_H - Math.min(CHART_H, Math.round((tokenPerSec / normBase) * CHART_H))
          : null;

        const chartW = bars.length * (BAR_W + BAR_GAP);
        const tpsLast = bars[bars.length - 1];
        const tpsPeak = Math.max(...bars, 1);
        const tooltipText = isConcurrency
          ? `Last 1s: ${tpsLast.toLocaleString()} tps  |  Target: ${tokenPerSec.toLocaleString()} tps  |  Peak: ${tpsPeak.toLocaleString()}  |  ${bars.length}s`
          : `Last 1s: ${tpsLast.toLocaleString()} tps  |  Peak: ${tpsPeak.toLocaleString()}  |  ${bars.length}s`;
        return (
          <Tooltip title={tooltipText}>
            <svg
              width={chartW}
              height={CHART_H}
              style={styles.svgBlock}
            >
              {bars.map((tps, i) => {
                const h = Math.max(1, Math.min(CHART_H, Math.round((tps / normBase) * CHART_H)));
                const isLast = i === bars.length - 1;
                // Blue-intensity scale: deep blue (colorPrimary) for high-TPS bars,
                // light blue (colorPrimaryBorder) for low-TPS bars, using fill-opacity
                // to interpolate smoothly.  Last bar always full opacity (active).
                const opacity = isLast ? 1 : Math.max(0.25, tps / normBase);
                const fill = isLast ? colors.svgBarActive : colors.svgBarActive;
                return (
                  <rect
                    key={i}
                    x={i * (BAR_W + BAR_GAP)}
                    y={CHART_H - h}
                    width={BAR_W}
                    height={h}
                    fill={fill}
                    fillOpacity={opacity}
                  />
                );
              })}
              {/* Dashed target-rate reference line — concurrency mode only */}
              {isConcurrency && targetLineY != null && (
                <line
                  x1={0}
                  y1={targetLineY}
                  x2={chartW}
                  y2={targetLineY}
                  stroke={colors.svgTargetLine}
                  strokeWidth={0.75}
                  strokeDasharray="2,2"
                />
              )}
            </svg>
          </Tooltip>
        );
      },
    },
    {
      title: "Thread ID",
      dataIndex: "thread_id",
      key: "thread_id",
      width: 260,
      ellipsis: true,
      render: (tid: string) => (
        <Text type="secondary" style={styles.monoSmallText}>
          {tid}
        </Text>
      ),
    },
    {
      title: "Streaming Output",
      key: "streaming_output",
      render: (_: unknown, record: ThreadSession) => {
        const streamText = record.stream_text ?? "";
        const isExpanded = expandedTokenLogId === record.thread_id;
        return (
          <div>
            <Button
              size="small"
              type={isExpanded ? "primary" : "default"}
              onClick={() => onToggleTokenLog?.(record.thread_id)}
              disabled={streamText.length === 0 && !isExpanded}
            >
              {isExpanded ? "Hide" : "Show"}
            </Button>
            {isExpanded && (
              <ThinkingStream
                stream={streamText}
                isRunning={!record.closed && !TERMINAL_STATUSES.has(record.status)}
              />
            )}
          </div>
        );
      },
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
          {!record.closed && !TERMINAL_STATUSES.has(record.status) && !frozen && (
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
