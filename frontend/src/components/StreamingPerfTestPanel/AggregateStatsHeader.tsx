import { Col, Row, Statistic, Tooltip, theme } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import type { AggregateStats } from "./aggregateStats";
import { styles } from "./AggregateStatsHeader.styles";

export interface AggregateStatsHeaderProps {
  /**
   * Pre-computed aggregate stats from useSessionManager's 1s sub-tick.
   * Passed as a prop (instead of the full sessions array) so this component
   * only re-renders once per second instead of on every 100ms token flush.
   */
  stats: AggregateStats;
  /**
   * True when at least one session is actively in the digest (streaming) phase.
   * Set reactively (not on the 1s tick) so the header can appear with "—"
   * placeholders immediately when streaming begins, before the first tick fires.
   */
  isDigesting?: boolean;
}

/**
 * Renders four aggregate throughput / latency statistics across all concurrent
 * streams:
 *
 *  - **Peak Sum Concurrent** — max total tps (sum across all streams) in any
 *    single 1-second window.
 *  - **Peak Single Stream** — max tps achieved by any one stream in any
 *    1-second window.
 *  - **Ave Concurrent** — mean total tps across all 1-second buckets.
 *  - **Max First-Token Latency** — max time from stream start to first
 *    `perf_token_batch` event across all sessions.
 *
 * Hidden when no session has per-second history yet.
 */
export function AggregateStatsHeader({ stats, isDigesting }: AggregateStatsHeaderProps) {
  const { token } = theme.useToken();
  const infoIconStyle = { color: token.colorTextTertiary, cursor: "help" as const };

  // Hide when no data and no streams are actively digesting.
  if (stats.sampleCount === 0 && !isDigesting) return null;

  // Show "—" placeholders while digesting has started but the first 1s tick
  // has not yet fired (sampleCount === 0 means no computed buckets yet).
  const hasData = stats.sampleCount > 0;
  // Show "—" when no data yet, or when the value is null (sub-second, unreliable).
  const fmt = (v: number | null): string | number => (hasData && v != null ? v : "—");
  // Only show "tps" suffix when the value is a real number; omit it for "—".
  const fmtSuffix = (v: number | null): string | undefined =>
    hasData && v != null ? "tps" : undefined;
  const fmtMs = (v: number | null): string => {
    if (!hasData) return "—";
    if (v == null) return "—";
    if (v < 1000) return `${Math.round(v)}ms`;
    return `${(v / 1000).toFixed(1)}s`;
  };

  const valueStyle = styles.valueStyle;

  return (
    <Row gutter={12} style={styles.row}>
      <Col span={4}>
        <Statistic
          title={
            <span>
              Peak Sum Read Batch{" "}
              <Tooltip title="Max total tokens/s summed across all read-batch streams in any single 1-second window. Each second, all stream tps_history values are summed; the peak of those sums is reported. Suspicious (out-of-sync) streams are excluded.">
                <InfoCircleOutlined style={infoIconStyle} />
              </Tooltip>
            </span>
          }
          value={fmt(stats.peakSumConcurrent)}
          suffix={fmtSuffix(stats.peakSumConcurrent)}
          styles={{ content: valueStyle }}
        />
      </Col>
      {stats.maxStableCount !== null && (
        <Col span={4}>
          <Statistic
            title={
              <span>
                Max Num Stable Streams{" "}
                <Tooltip title="Maximum number of concurrency-mode streams that were simultaneously stable in any single 1-second window. A stream is stable when ≥10% of its prior TPS history (min 3 s) exceeded 90% of the target rate.">
                  <InfoCircleOutlined style={infoIconStyle} />
                </Tooltip>
              </span>
            }
            value={hasData ? stats.maxStableCount : "—"}
            styles={{ content: valueStyle }}
          />
        </Col>
      )}
      {stats.maxStableCount === null && (
        <Col span={4}>
          <Statistic
            title={
              <span>
                Max Num Digesting Streams{" "}
                <Tooltip title="Maximum number of streams simultaneously in the digest (streaming) phase in any single 1-second window.">
                  <InfoCircleOutlined style={infoIconStyle} />
                </Tooltip>
              </span>
            }
            value={hasData ? stats.maxDigestingCount : "—"}
            styles={{ content: valueStyle }}
          />
        </Col>
      )}
      <Col span={4}>
        <Statistic
          title={
            <span>
              Peak Single Stream{" "}
              <Tooltip title="Max tokens/s achieved by any single stream in any 1-second window. peak = max(max(tps_history) for each stream).">
                <InfoCircleOutlined style={infoIconStyle} />
              </Tooltip>
            </span>
          }
          value={fmt(stats.peakSingleStream)}
          suffix={fmtSuffix(stats.peakSingleStream)}
          styles={{ content: valueStyle }}
        />
      </Col>
      <Col span={4}>
        <Statistic
          title={
            <span>
              Ave Read Batch{" "}
              <Tooltip title="Mean total tokens/s across all 1-second windows. Per-second sums (across all streams) are averaged over every bucket that had at least one stream active. Suspicious (out-of-sync) streams are excluded.">
                <InfoCircleOutlined style={infoIconStyle} />
              </Tooltip>
            </span>
          }
          value={fmt(stats.aveConcurrent)}
          suffix={fmtSuffix(stats.aveConcurrent)}
          styles={{ content: valueStyle }}
        />
      </Col>
      <Col span={4}>
        <Statistic
          title={
            <span>
              Max First-Token Latency{" "}
              <Tooltip title="Maximum time from stream start until the first perf_token_batch event, across all sessions. Measures how long the slowest stream waited before tokens began flowing.">
                <InfoCircleOutlined style={infoIconStyle} />
              </Tooltip>
            </span>
          }
          value={fmtMs(stats.maxFirstTokenLatencyMs)}
          styles={{ content: valueStyle }}
        />
      </Col>
    </Row>
  );
}
