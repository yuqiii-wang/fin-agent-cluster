import { Badge, Button, Space, Tag, Tooltip, Typography } from "antd";
import type { GlobalToken } from "antd/es/theme/interface";
import type { ColumnsType } from "antd/es/table";
import { CompressOutlined, InfoCircleOutlined, PauseCircleOutlined, UnorderedListOutlined } from "@ant-design/icons";
import type { ThreadSession } from "./types";
import { TERMINAL_STATUSES } from "./types";
import { isSessionStable } from "./useSessionManager";
import { isSessionSuspicious } from "./aggregateStats";
import { styles, getColumnColors } from "./columns.styles";
import { StreamingTaskOutput } from "../../services/streaming/core";

const { Text } = Typography;

/** One labelled row in the Identity stack cell. */
interface IdentityRowProps {
  label: string;
  /** The full value — UUID or number. Shown in Tooltip; display truncates UUIDs. */
  value: string;
  /** When true the value is displayed as-is (not truncated). */
  numeric?: boolean;
}

function IdentityRow({ label, value, numeric }: IdentityRowProps) {
  const display = numeric ? value : value;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, lineHeight: "18px" }}>
      <span style={{ color: "#8c8c8c", width: 44, flexShrink: 0, fontSize: 10 }}>{label}</span>
      <Text code style={{ fontSize: 10, userSelect: "all" }}>{display}</Text>
    </div>
  );
}

/**
 * Identity cell: collapsed = Stream ID only (click to expand).
 * Expanded = full stack: Thread, Node, Leaf, Task, Stream.
 * Falls back gracefully before the `started` event arrives (stream_id is null).
 * Controlled: parent manages accordion state via `expanded` + `onToggle`.
 */
function IdentityStack({ record, expanded, onToggle }: { record: ThreadSession; expanded: boolean; onToggle: () => void }) {

  if (!expanded) {
    return (
      <div
        style={{ fontFamily: "monospace", cursor: "pointer" }}
        onClick={onToggle}
        title="Click to expand IDs"
      >
        {record.stream_id ? (
          <IdentityRow label="Stream" value={record.stream_id} />
        ) : record.thread_id ? (
          <IdentityRow label="Thread" value={record.thread_id} />
        ) : (
          <Text type="secondary" style={{ fontSize: 10 }}>—</Text>
        )}
      </div>
    );
  }

  return (
    <div style={{ fontFamily: "monospace", position: "relative" }}>
      <Tooltip title="Collapse">
        <Button
          type="text"
          size="small"
          icon={<CompressOutlined />}
          onClick={onToggle}
          style={{ position: "absolute", top: 0, right: 0, padding: 0, height: 16, width: 16, minWidth: 16, fontSize: 10 }}
        />
      </Tooltip>
      <IdentityRow label="Thread" value={record.thread_id} />
      {record.node_id      && <IdentityRow label="Node"   value={record.node_id} />}
      {record.task_id     && <IdentityRow label="Task"   value={record.task_id} />}
      {record.task_id != null && <IdentityRow label="TaskUUID" value={record.task_id} />}
      {record.stream_id    && <IdentityRow label="Stream" value={record.stream_id} />}
    </div>
  );
}

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
  tokenPerSec: number = 100,
  expandedTokenLogId?: string | null,
  onToggleTokenLog?: (thread_id: string) => void,
  expandedIdentityId?: string | null,
  onToggleIdentity?: (thread_id: string) => void,
): ColumnsType<ThreadSession> {
  const colors = token ? getColumnColors(token) : getColumnColors({
    colorPrimary: "#1677ff",
    colorPrimaryBorder: "#91caff",
    colorWarning: "#faad14",
    colorTextTertiary: "#8c8c8c",
  });
  return [
    {
      title: "Identity",
      key: "identity",
      width: 320,
      render: (_: unknown, record: ThreadSession) => (
        <IdentityStack
          record={record}
          expanded={expandedIdentityId === record.thread_id}
          onToggle={() => onToggleIdentity?.(record.thread_id)}
        />
      ),
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
          lost:       { badgeStatus: "error",      tagColor: "magenta",    label: "Lost"        },
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
        if (status === "timeout") {
          const tooltipTitle =
            record.close_reason ??
            "Session exceeded the configured timeout without completing the full lifecycle. Check browser console and backend logs for details.";
          return (
            <Tooltip title={tooltipTitle} color="volcano">
              {badge}
            </Tooltip>
          );
        }
        if (status === "lost") {
          return (
            <Tooltip title="Backend reported completed but no tokens were delivered after 5s. Tokens were lost in transit — check Centrifugo consumer lag on fin:llm:tokens." color="magenta">
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
          Ingest Time{" "}
          <Tooltip title="Elapsed time for the ingest phase (writing tokens to the Redis perf stream). Shows live progress while running; shows final elapsed time once complete.">
            <InfoCircleOutlined style={colors.infoIcon} />
          </Tooltip>
        </span>
      ),
      key: "ingest",
      width: 160,
      align: "right",
      render: (_: unknown, record: ThreadSession) => {
        const { ingest_status, ingest_produced, ingest_ms } = record;
        if (!ingest_status && ingest_produced === undefined) return <Text type="secondary">—</Text>;
        const produced = ingest_produced ?? 0;
        const timeLabel = ingest_ms != null
          ? ingest_ms >= 1000
            ? `${(ingest_ms / 1000).toFixed(2)}s`
            : `${ingest_ms}ms`
          : null;
        if (ingest_status === "completed") {
          return (
            <Tooltip title={`Ingest complete — ${produced.toLocaleString()} tokens`}>
              <Badge status="success" text={<Text style={styles.smallText}>{timeLabel ?? produced.toLocaleString()}</Text>} />
            </Tooltip>
          );
        }
        if (ingest_status === "timeout") {
          // In concurrency mode timeout is the expected end state — show success.
          const badgeStatus = record.test_mode === "concurrency" ? "success" : "warning";
          const tooltipText = record.test_mode === "concurrency" ? "Ingest ended (timeout — expected)" : "Ingest timed out";
          return (
            <Tooltip title={`${tooltipText} — ${produced.toLocaleString()} tokens`}>
              <Badge status={badgeStatus} text={<Text style={styles.smallText}>{timeLabel ?? produced.toLocaleString()}</Text>} />
            </Tooltip>
          );
        }
        return <Text style={styles.smallText}>{timeLabel ?? produced.toLocaleString()}</Text>;
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
        const { batch_first, batch_max, batch_ave, batch_last } = record;
        if (batch_first === undefined) return <Text type="secondary">—</Text>;
        return (
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
        );
      },
    },
    {
      title: (
        <span>
          Progress{" "}
          <Tooltip title={`Throughput: tokens received / target. Concurrency: elapsed time since first token / timeout (per stream). Stable = last ${Math.max(3, Math.ceil(timeoutSecs * 0.2))}s window (${timeoutSecs}s × 20%) — ≥70% of 1-second buckets must reach 90% of the ${tokenPerSec} tps target.`}>
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
          const stable = isSessionStable(record.tps_history ?? [], tokenPerSec, timeoutSecs);
          return (
              <Tooltip title={`${(elapsedMs / 1000).toFixed(1)}s / ${timeoutSecs}s${stable ? ` — TPS stable: ≥70% of last ${Math.max(3, Math.ceil(timeoutSecs * 0.1))} 1-second buckets exceeded 90% of the ${tokenPerSec} tps target.` : ""}`}>
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
        const rawElapsedMs = endMs - digestStart;
        // Floor the elapsed window with ingest_ms (actual wall-clock work) so that
        // sub-millisecond digest windows (Centrifugo delivers all tokens in <1ms)
        // don't produce astronomically inflated TPS figures.  Fall back to 10ms
        // when ingest_ms is unavailable.
        const floorMs = record.ingest_ms != null && record.ingest_ms > 0 ? record.ingest_ms : 10;
        const elapsedMs = Math.max(rawElapsedMs, floorMs);
        const elapsed = elapsedMs / 1000;
        const rate = record.tokens > 0 ? (record.tokens / elapsed) : 0;
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
        // Out-of-sync: session is digesting but tokens stopped flowing. Show — so
        // the growing elapsed time is not shown for a stalled stream.
        if (!isFrozenDuration && isSessionSuspicious(record, Date.now())) {
          return <Text type="secondary">—</Text>;
        }
        const endMs = isFrozenDuration ? record.last_token_ms : Date.now();
        const elapsedMs = Math.max(0, endMs - startMs);
        if (elapsedMs === 0) return <Text type="secondary">—</Text>;
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
        // Fit bars within the column width (180px) minus a small padding.
        const COLUMN_W = 172;
        const MAX_BARS = Math.floor(COLUMN_W / (BAR_W + BAR_GAP));

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
            <div style={{ width: COLUMN_W, overflow: "hidden" }}>
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
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: "Streaming Output",
      key: "streaming_output",
      render: (_: unknown, record: ThreadSession) => {
        const streamText = record.stream_text ?? "";
        const isExpanded = expandedTokenLogId === record.thread_id;
        const isRunning = !record.closed && !TERMINAL_STATUSES.has(record.status);
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
              <StreamingTaskOutput
                stream={streamText}
                isRunning={isRunning}
                tokenCount={record.tokens > 0 ? record.tokens : undefined}
                status={record.status}
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
