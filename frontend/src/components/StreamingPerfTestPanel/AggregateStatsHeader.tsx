import { useMemo } from "react";
import { Col, Row, Statistic, Tooltip } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import type { ThreadSession } from "./types";
import { computeAggregateStats } from "./aggregateStats";

export interface AggregateStatsHeaderProps {
  sessions: ThreadSession[];
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
export function AggregateStatsHeader({ sessions }: AggregateStatsHeaderProps) {
  const stats = useMemo(() => computeAggregateStats(sessions), [sessions]);

  if (stats.sampleCount === 0) return null;

  const fmt = (v: number | null) => (v == null ? 0 : v);
  const fmtMs = (v: number | null) => {
    if (v == null) return "—";
    if (v < 1000) return `${Math.round(v)}ms`;
    return `${(v / 1000).toFixed(1)}s`;
  };

  return (
    <Row gutter={12} style={{ marginTop: 8 }}>
      <Col span={6}>
        <Statistic
          title={
            <span>
              Peak Sum Concurrent{" "}
              <Tooltip title="Max total tokens/s summed across all concurrent streams in any single 1-second window. Each second, all stream tps_history values are summed; the peak of those sums is reported.">
                <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
              </Tooltip>
            </span>
          }
          value={fmt(stats.peakSumConcurrent)}
          suffix="tps"
        />
      </Col>
      <Col span={6}>
        <Statistic
          title={
            <span>
              Peak Single Stream{" "}
              <Tooltip title="Max tokens/s achieved by any single stream in any 1-second window. peak = max(max(tps_history) for each stream).">
                <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
              </Tooltip>
            </span>
          }
          value={fmt(stats.peakSingleStream)}
          suffix="tps"
        />
      </Col>
      <Col span={6}>
        <Statistic
          title={
            <span>
              Ave Concurrent{" "}
              <Tooltip title="Mean total tokens/s across all 1-second windows. Per-second sums (across all streams) are averaged over every bucket that had at least one stream active.">
                <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
              </Tooltip>
            </span>
          }
          value={fmt(stats.aveConcurrent)}
          suffix="tps"
        />
      </Col>
      <Col span={6}>
        <Statistic
          title={
            <span>
              Max First-Token Latency{" "}
              <Tooltip title="Maximum time from stream start until the first perf_token_batch event, across all sessions. Measures how long the slowest stream waited before tokens began flowing.">
                <InfoCircleOutlined style={{ color: "#8c8c8c", cursor: "help" }} />
              </Tooltip>
            </span>
          }
          value={fmtMs(stats.maxFirstTokenLatencyMs)}
          valueStyle={{ fontSize: 20 }}
        />
      </Col>
    </Row>
  );
}
