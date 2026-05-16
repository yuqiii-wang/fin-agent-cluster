/**
 * ConcurrencyTest — grid component for monitoring concurrent streaming threads.
 *
 * Columns (per thread):
 *   thread_id | status | latency to conclusion | streaming TPS | acks sent | acks confirmed | ack %
 *
 * Aggregation headers (above the table):
 *   peak concurrency | peak TPS | max latency | min latency
 *
 * Some columns are updated once per completed event from SSE backend;
 * others (TPS, ack counts) are updated per-second by the UI audit ticker.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLatestRef } from '../../hooks/refUtils';
import { Badge, Button, Space, Statistic, Table, Tag, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined, StopOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { QueryResponse, SseInfo } from '../../types';
import { isThreadTerminal, isThreadActive } from '../../constants/lifecycleStatus';
import { STATUS_TAG_COLOR } from '../../constants/statusColors';
import { cancelThread } from '../../api/threads';
import { useConcurrencyThread } from './useConcurrencyThread';
import StreamingDisplay from './StreamingDisplay';
import type { ThreadRow } from './types';

const { Text, Title } = Typography;

/** Session-local Centrifugo bootstrap info for a submitted thread. */
interface LiveInfo {
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
}

interface Props {
  /** Initial query responses from the concurrent submission burst. */
  initialResults: QueryResponse[];
  /** Called when the user clicks a thread row to navigate to its ThreadView. */
  onSelectThread?: (threadId: string) => void;
  /** Called whenever a thread's status changes (for syncing history sidebar). */
  onStatusUpdate?: (threadId: string, status: string) => void;
}

/** Headless component: wires Centrifugo subscriptions and registers the streamTextRef. */
const ThreadWatcher: React.FC<{
  row: ThreadRow;
  liveInfo: LiveInfo;
  onUpdate: (threadId: string, update: Partial<ThreadRow>) => void;
  onRegisterRef: (threadId: string, ref: React.MutableRefObject<string>) => void;
}> = ({ row, liveInfo, onUpdate, onRegisterRef }) => {
  const done = isThreadTerminal(row.status);
  const { streamTextRef } = useConcurrencyThread({
    threadId: row.threadId,
    sseInfo: liveInfo.sseInfo,
    llmInfo: liveInfo.llmInfo,
    submitTime: row.submitTime,
    done,
    onUpdate,
  });
  const onRegisterRefRef = useLatestRef(onRegisterRef);
  useEffect(() => {
    onRegisterRefRef.current(row.threadId, streamTextRef);
  // Register once on mount — streamTextRef identity is stable.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
};

function statusTag(status: ThreadRow['status']): React.ReactNode {
  const color = STATUS_TAG_COLOR[status] ?? 'default';
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  return <Tag color={color}>{label}</Tag>;
}

const ConcurrencyTest: React.FC<Props> = ({ initialResults, onSelectThread, onStatusUpdate }) => {
  const submitTime = useRef(Date.now());
  const onStatusUpdateRef = useLatestRef(onStatusUpdate);

  // Initialise one row per submitted thread.
  // Use the status from the API response (typically 'received') so the grid
  // immediately reflects the backend state instead of showing 'pending'.
  const [rows, setRows] = useState<ThreadRow[]>(() =>
    initialResults.map((r) => ({
      threadId: r.thread_id,
      submitTime: submitTime.current,
      status: (r.status as ThreadRow['status']) ?? 'pending',
      streamTaskStatus: null,
      latencyToConclusion: null,
      tokensReceived: 0,
      maxSeq: 0,
      totalSeq: null,
      currentTps: 0,
      acksSent: 0,
      acksConfirmed: 0,
      streamStart: null,
      streamEnd: null,
      llmMqConnected: false,
    })),
  );

  // Live Centrifugo bootstrap info keyed by thread_id.
  const [liveMap] = useState<Record<string, LiveInfo>>(() => {
    const m: Record<string, LiveInfo> = {};
    for (const r of initialResults) {
      m[r.thread_id] = { sseInfo: r.sse ?? null, llmInfo: r.llm ?? null };
    }
    return m;
  });

  // Tracks the historical peak of the combined TPS sum across all streaming MQ threads.
  const peakTpsSumRef = useRef(0);

  // streamTextRef per thread, registered by ThreadWatcher on mount.
  const streamTextRefsMap = useRef<Map<string, React.MutableRefObject<string>>>(new Map());
  const fallbackEmptyRef = useRef('');

  const handleRegisterStreamRef = useCallback(
    (threadId: string, ref: React.MutableRefObject<string>) => {
      streamTextRefsMap.current.set(threadId, ref);
    },
    [],
  );

  // Tracks which thread stream panels are visible (show/hide toggle).
  const [visibleStreams, setVisibleStreams] = useState<Set<string>>(new Set());

  const toggleStream = useCallback((threadId: string) => {
    setVisibleStreams((prev) => {
      const next = new Set(prev);
      if (next.has(threadId)) next.delete(threadId);
      else next.add(threadId);
      return next;
    });
  }, []);

  const handleUpdate = useCallback((threadId: string, update: Partial<ThreadRow>) => {
    if (update.status !== undefined) {
      onStatusUpdateRef.current?.(threadId, update.status);
    }
    setRows((prev) =>
      prev.map((r) => (r.threadId === threadId ? { ...r, ...update } : r)),
    );
  }, []);

  const [cancellingAll, setCancellingAll] = useState(false);

  const handleCancelAll = useCallback(async () => {
    const active = rows.filter((r) => !isThreadTerminal(r.status));
    if (active.length === 0) return;
    setCancellingAll(true);
    try {
      await Promise.allSettled(active.map((r) => cancelThread(r.threadId)));
    } finally {
      setCancellingAll(false);
    }
  }, [rows]);

  // Per-second TPS ticker: recompute live TPS from token counters.
  useEffect(() => {
    const tid = setInterval(() => {
      setRows((prev) => {
        const updated = prev.map((r) => {
          if (r.streamStart === null || r.streamEnd !== null) return r;
          const elapsedSec = (Date.now() - r.streamStart) / 1000;
          const tps = elapsedSec > 0 ? Math.round((r.tokensReceived / elapsedSec) * 10) / 10 : 0;
          return { ...r, currentTps: tps };
        });
        // Update peak combined TPS sum across all threads with active MQ streaming.
        const currentSum = updated
          .filter((r) => r.llmMqConnected && r.streamEnd === null && r.currentTps > 0)
          .reduce((sum, r) => sum + r.currentTps, 0);
        const rounded = Math.round(currentSum * 10) / 10;
        if (rounded > peakTpsSumRef.current) peakTpsSumRef.current = rounded;
        return updated;
      });
    }, 1000);
    return () => clearInterval(tid);
  }, []);

  // ── Aggregation metrics ──────────────────────────────────────────────────
  const agg = useMemo(() => {
    const now = Date.now();
    const streaming = rows.filter((r) => isThreadActive(r.status));

    // Sweep-line over [streamStart, streamEnd] intervals to find the max
    // number of threads that were running simultaneously at any point.
    const events: [number, number][] = [];
    for (const r of rows) {
      if (r.streamStart === null) continue;
      events.push([r.streamStart, 1]);
      events.push([r.streamEnd ?? now, -1]);
    }
    // Sort by time; process ends (-1) before starts (+1) on ties so that a
    // thread ending exactly when another starts is not counted as overlapping.
    events.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    let _count = 0;
    let peakConcurrency = 0;
    for (const [, delta] of events) {
      _count += delta;
      if (_count > peakConcurrency) peakConcurrency = _count;
    }
    const peakTps = peakTpsSumRef.current;
    const latencies = rows.filter((r) => r.latencyToConclusion !== null).map((r) => r.latencyToConclusion as number);
    const maxLatency = latencies.length > 0 ? Math.max(...latencies) : null;
    const minLatency = latencies.length > 0 ? Math.min(...latencies) : null;
    return { peakConcurrency, peakTps, maxLatency, minLatency, activeCount: streaming.length };
  }, [rows]);

  const columns: ColumnsType<ThreadRow> = [
    {
      title: 'Thread ID',
      dataIndex: 'threadId',
      width: 320,
      render: (v: string) =>
        onSelectThread ? (
          <Text
            code
            copyable
            style={{ fontSize: 11, cursor: 'pointer', color: '#1677ff' }}
            onClick={() => onSelectThread(v)}
          >
            {v}
          </Text>
        ) : (
          <Text code copyable style={{ fontSize: 11 }}>
            {v}
          </Text>
        ),
    },
    {
      title: 'Thread Status',
      dataIndex: 'status',
      width: 130,
      render: (v: ThreadRow['status']) => statusTag(v),
    },
    {
      title: (
        <Space size={4}>
          Stream Task
          <Tooltip title="Status of the stream_conclusion Celery task running under conclusion_node. Tracks the LLM streaming worker lifecycle independently from the thread status.">
            <QuestionCircleOutlined style={{ color: '#8c8c8c', fontSize: 12, cursor: 'help' }} />
          </Tooltip>
        </Space>
      ),
      dataIndex: 'streamTaskStatus',
      width: 140,
      render: (v: ThreadRow['streamTaskStatus']) => {
        if (v === null) return <Text type="secondary">—</Text>;
        const color = STATUS_TAG_COLOR[v] ?? 'default';
        const label = v.charAt(0).toUpperCase() + v.slice(1);
        return <Tag color={color}>{label}</Tag>;
      },
    },
    {
      title: 'Latency to Conclusion',
      dataIndex: 'latencyToConclusion',
      width: 180,
      render: (v: number | null) => {
        if (v === null) return <Text type="secondary">—</Text>;
        if (v >= 1000) return <Text>{(v / 1000).toFixed(1)} s</Text>;
        return <Text>{v.toLocaleString()} ms</Text>;
      },
    },
    // ── LLM Streaming ───────────────────────────────────────────────────────
    {
      title: 'LLM Streaming',
      children: [
        {
          title: 'MQ',
          dataIndex: 'llmMqConnected',
          width: 260,
          render: (v: boolean, r: ThreadRow) => {
            const isVisible = visibleStreams.has(r.threadId);
            const textRef = streamTextRefsMap.current.get(r.threadId) ?? fallbackEmptyRef;
            return (
              <div>
                <Space size={6}>
                  <Badge status={v ? 'success' : 'default'} text={v ? 'On' : 'Off'} />
                  <Button
                    size="small"
                    type="text"
                    style={{ padding: '0 4px', fontSize: 11 }}
                    onClick={(e) => { e.stopPropagation(); toggleStream(r.threadId); }}
                  >
                    {isVisible ? 'Hide' : 'Show'}
                  </Button>
                </Space>
                {isVisible && (
                  <StreamingDisplay
                    textRef={textRef}
                    isLive={v && r.streamEnd === null}
                  />
                )}
              </div>
            );
          },
        },
        {
          title: 'TPS',
          dataIndex: 'currentTps',
          width: 110,
          render: (v: number, r: ThreadRow) =>
            r.streamStart !== null ? (
              <Badge
                status={r.streamEnd === null ? 'processing' : 'default'}
                text={`${v} tok/s`}
              />
            ) : (
              <Text type="secondary">—</Text>
            ),
        },
        {
          title: 'Tokens',
          dataIndex: 'tokensReceived',
          width: 110,
          render: (v: number, r: ThreadRow) => (
            <Text>
              {v}{r.totalSeq !== null ? ` / ${r.totalSeq}` : ''}
            </Text>
          ),
        },
      ],
    },
    // ── SSE Notification ACKs ────────────────────────────────────────────────
    {
      title: 'SSE Notification',
      children: [
        {
          title: 'Sent',
          dataIndex: 'acksSent',
          width: 70,
          render: (v: number) => <Text>{v}</Text>,
        },
        {
          title: 'Confirmed',
          dataIndex: 'acksConfirmed',
          width: 90,
          render: (v: number) => <Text>{v}</Text>,
        },
        {
          title: 'ACK %',
          width: 80,
          render: (_: unknown, r: ThreadRow) => {
            if (r.acksSent === 0) return <Text type="secondary">—</Text>;
            const pct = Math.round((r.acksConfirmed / r.acksSent) * 100);
            return (
              <Tag color={pct === 100 ? 'green' : pct >= 80 ? 'orange' : 'red'}>
                {pct}%
              </Tag>
            );
          },
        },
      ],
    },
  ];

  return (
    <div style={{ padding: '0 4px' }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        Concurrency Test — {initialResults.length} threads
      </Title>

      {/* Aggregation header */}
      <Space size={32} style={{ marginBottom: 20, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Statistic
          title="Active / Peak Concurrency"
          value={`${agg.activeCount} / ${agg.peakConcurrency}`}
          styles={{ content: { fontSize: 20 } }}
        />
        <Statistic
          title="Peak TPS (thread sum)"
          value={agg.peakTps}
          suffix="tok/s"
          styles={{ content: { fontSize: 20 } }}
        />
        <Statistic
          title="Max Latency to Conclusion"
          value={agg.maxLatency !== null ? (agg.maxLatency >= 1000 ? (agg.maxLatency / 1000).toFixed(1) : agg.maxLatency) : '—'}
          suffix={agg.maxLatency !== null ? (agg.maxLatency >= 1000 ? 's' : 'ms') : ''}
          styles={{ content: { fontSize: 20 } }}
        />
        <Statistic
          title="Min Latency to Conclusion"
          value={agg.minLatency !== null ? (agg.minLatency >= 1000 ? (agg.minLatency / 1000).toFixed(1) : agg.minLatency) : '—'}
          suffix={agg.minLatency !== null ? (agg.minLatency >= 1000 ? 's' : 'ms') : ''}
          styles={{ content: { fontSize: 20 } }}
        />
        <Button
          danger
          icon={<StopOutlined />}
          loading={cancellingAll}
          disabled={agg.activeCount === 0}
          onClick={handleCancelAll}
        >
          Cancel All
        </Button>
      </Space>

      {/* Per-thread grid */}
      <Table<ThreadRow>
        dataSource={rows}
        columns={columns}
        rowKey="threadId"
        pagination={false}
        size="small"
        bordered
        virtual
        scroll={{ x: 1490, y: 600 }}
        onRow={onSelectThread ? (r) => ({
          onClick: () => onSelectThread(r.threadId),
          style: { cursor: 'pointer' },
        }) : undefined}
      />

      {/* Headless per-thread watchers — always mounted to keep subscriptions alive. */}
      {rows.map((r) => (
        <ThreadWatcher
          key={r.threadId}
          row={r}
          liveInfo={liveMap[r.threadId] ?? { sseInfo: null, llmInfo: null }}
          onUpdate={handleUpdate}
          onRegisterRef={handleRegisterStreamRef}
        />
      ))}
    </div>
  );
};

export default ConcurrencyTest;
