/**
 * StackCandleStickChart — stacks multiple OHLCV candlestick charts vertically,
 * each representing a different instrument, with a shared / synchronized time-axis.
 *
 * Data shape:
 *   items: { symbol: string; label: string; df_split: DfSplit }[]
 *
 * Time-axis synchronization:
 *   Each chart subscribes to the others' visible-time-range changes and mirrors
 *   them, giving the appearance of a single shared x-axis.  A re-entrancy flag
 *   prevents infinite update loops.
 */

import React, { useEffect, useRef, useMemo, useState } from 'react';
import { Select, Typography } from 'antd';
import { createChart, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts';
import type { DfSplit } from '../StatsDataFrame';
import type { IChartApi } from 'lightweight-charts';

const { Text } = Typography;

type Overlay = 'sma_20' | 'rsi_14';

const OVERLAY_COLOR: Record<Overlay, string> = {
  sma_20: '#f4c430',
  rsi_14: '#a78bfa',
};

const OVERLAY_LABEL: Record<Overlay, string> = {
  sma_20: 'SMA 20',
  rsi_14: 'RSI 14',
};

const ALL_OVERLAYS: Overlay[] = ['sma_20', 'rsi_14'];

export interface StackCandleItem {
  symbol: string;
  label: string;
  df_split: DfSplit;
}

interface Props {
  items: StackCandleItem[];
  /** Per-chart height in pixels. */
  chartHeight?: number;
}

const CHART_THEME = {
  background: '#1a1d23',
  text: '#9B9EA4',
  grid: '#2B2F38',
  border: '#2B2F38',
} as const;

/** Build sorted, deduped candle rows from a df_split. */
function buildCandleRows(dfSplit: DfSplit) {
  const { index, columns, data } = dfSplit;
  const openIdx   = columns.indexOf('open');
  const highIdx   = columns.indexOf('high');
  const lowIdx    = columns.indexOf('low');
  const closeIdx  = columns.indexOf('close');
  const volumeIdx = columns.indexOf('volume');
  const smaIdx    = columns.indexOf('sma_20');
  const rsiIdx    = columns.indexOf('rsi_14');

  if (openIdx === -1 || highIdx === -1 || lowIdx === -1 || closeIdx === -1) return null;

  const rows = index
    .map((date, i) => ({
      time:   date as string,
      open:   (data[i]?.[openIdx]   ?? 0) as number,
      high:   (data[i]?.[highIdx]   ?? 0) as number,
      low:    (data[i]?.[lowIdx]    ?? 0) as number,
      close:  (data[i]?.[closeIdx]  ?? 0) as number,
      volume: volumeIdx !== -1 ? ((data[i]?.[volumeIdx] ?? 0) as number) : 0,
      sma20:  smaIdx !== -1 ? ((data[i]?.[smaIdx] ?? null) as number | null) : null,
      rsi14:  rsiIdx !== -1 ? ((data[i]?.[rsiIdx] ?? null) as number | null) : null,
    }))
    .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
    .filter((d, i, arr) => i === 0 || d.time !== arr[i - 1].time);

  return { rows, hasVolume: volumeIdx !== -1, hasSma20: smaIdx !== -1, hasRsi14: rsiIdx !== -1 };
}

const SinglePane: React.FC<{
  item: StackCandleItem;
  chartHeight: number;
  activeOverlays: Set<Overlay>;
  onChartReady: (api: IChartApi) => void;
  globalRange: { from: string; to: string } | null;
}> = ({ item, chartHeight, activeOverlays, onChartReady, globalRange }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const rsiActive = activeOverlays.has('rsi_14');
  // Expand chart height to accommodate RSI sub-pane.
  const effectiveHeight = rsiActive ? chartHeight + 80 : chartHeight;
  const ohlcBottom = rsiActive ? 0.44 : 0.25;

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: effectiveHeight,
      layout: {
        background: { color: CHART_THEME.background },
        textColor: CHART_THEME.text,
      },
      grid: {
        vertLines: { color: CHART_THEME.grid },
        horzLines: { color: CHART_THEME.grid },
      },
      timeScale: {
        borderColor: CHART_THEME.border,
        timeVisible: true,
        rightOffset: 5,
      },
      rightPriceScale: {
        borderColor: CHART_THEME.border,
        scaleMargins: { top: 0.05, bottom: ohlcBottom },
      },
      crosshair: { mode: 1 },
    });

    const parsed = buildCandleRows(item.df_split);
    if (parsed) {
      const { rows, hasVolume, hasSma20, hasRsi14 } = parsed;

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
      });
      candleSeries.setData(
        rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
      );

      if (hasSma20 && activeOverlays.has('sma_20')) {
        const smaSeries = chart.addSeries(LineSeries, {
          color: OVERLAY_COLOR.sma_20,
          lineWidth: 1,
          priceScaleId: 'right',
          lastValueVisible: false,
          priceLineVisible: false,
        });
        smaSeries.setData(
          rows
            .filter((d) => d.sma20 !== null)
            .map(({ time, sma20 }) => ({ time, value: sma20 as number })),
        );
      }

      if (hasVolume) {
        const volSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        volSeries.setData(
          rows.map(({ time, open, close, volume }) => ({
            time,
            value: volume,
            color: close >= open ? 'rgba(38,166,154,0.5)' : 'rgba(239,83,80,0.5)',
          })),
        );
      }

      if (hasRsi14 && activeOverlays.has('rsi_14')) {
        const rsiSeries = chart.addSeries(LineSeries, {
          color: OVERLAY_COLOR.rsi_14,
          lineWidth: 1,
          priceScaleId: 'rsi',
          lastValueVisible: false,
          priceLineVisible: false,
        });
        chart.priceScale('rsi').applyOptions({
          scaleMargins: { top: 0.56, bottom: 0.22 },
          borderVisible: false,
        });
        rsiSeries.setData(
          rows
            .filter((d) => d.rsi14 !== null)
            .map(({ time, rsi14 }) => ({ time, value: rsi14 as number })),
        );
      }

      chart.timeScale().fitContent();
    }

    chartRef.current = chart;
    onChartReady(chart);

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.symbol, effectiveHeight, activeOverlays]);

  // Apply the global (union) time range so all panes share the same x-axis span.
  // Runs after the chart is (re)built and whenever globalRange changes.
  useEffect(() => {
    if (!chartRef.current || !globalRange) return;
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      chartRef.current.timeScale().setVisibleRange(globalRange as any);
    } catch {
      // chart may have been removed
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.symbol, effectiveHeight, activeOverlays, globalRange]);

  return (
    <div style={{ marginBottom: 2 }}>
      <div
        style={{
          padding: '3px 8px',
          background: '#20242d',
          borderLeft: '3px solid #26a69a',
          marginBottom: 1,
        }}
      >
        <Text style={{ fontSize: 11, color: '#9B9EA4' }}>
          {item.label}&nbsp;
          <span style={{ color: '#5a5e6b', fontFamily: 'monospace' }}>{item.symbol}</span>
        </Text>
      </div>
      <div ref={containerRef} />
    </div>
  );
};

const StackCandleStickChart: React.FC<Props> = ({ items, chartHeight = 180 }) => {
  const chartsRef = useRef<IChartApi[]>([]);
  const syncingRef = useRef(false);
  const [activeOverlays, setActiveOverlays] = useState<Set<Overlay>>(new Set());

  // Compute the union (max) time range across all items so every pane starts
  // with the same x-axis span regardless of individual data coverage.
  const globalRange = useMemo<{ from: string; to: string } | null>(() => {
    let from = '';
    let to = '';
    for (const item of items) {
      for (const t of item.df_split.index) {
        const ts = t as string;
        if (!from || ts < from) from = ts;
        if (!to || ts > to) to = ts;
      }
    }
    return from && to ? { from, to } : null;
  }, [items]);

  // Union of available overlay columns across all items.
  const availableOverlays = useMemo<Overlay[]>(() => {
    const unionCols = new Set<string>();
    items.forEach((item) => item.df_split.columns.forEach((c) => unionCols.add(c)));
    return ALL_OVERLAYS.filter((o) => unionCols.has(o));
  }, [items]);

  // Reset chart registry on items change.
  const itemKeys = useMemo(() => items.map((i) => i.symbol).join(','), [items]);
  useEffect(() => {
    chartsRef.current = [];
  }, [itemKeys]);

  const handleChartReady = (chart: IChartApi) => {
    const charts = chartsRef.current;
    charts.push(chart);

    // Subscribe this chart to sync all others when its time range changes.
    chart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (syncingRef.current || !range) return;
      syncingRef.current = true;
      charts.forEach((other) => {
        if (other !== chart) {
          try {
            other.timeScale().setVisibleRange(range);
          } catch {
            // chart may have been removed
          }
        }
      });
      syncingRef.current = false;
    });
  };

  if (!items.length) {
    return <Text type="secondary" style={{ fontSize: 12 }}>No data</Text>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {availableOverlays.length > 0 && (
        <div style={{ display: 'flex', gap: 8, padding: '4px 8px', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: '#9B9EA4', flexShrink: 0 }}>Overlay:</span>
          <Select
            mode="multiple"
            size="small"
            value={Array.from(activeOverlays)}
            onChange={(values: string[]) => setActiveOverlays(new Set(values as Overlay[]))}
            options={availableOverlays.map((o) => ({
              value: o,
              label: <span style={{ color: OVERLAY_COLOR[o], fontSize: 12 }}>{OVERLAY_LABEL[o]}</span>,
            }))}
            style={{ minWidth: 140 }}
            placeholder="Add overlay…"
            popupMatchSelectWidth={false}
          />
        </div>
      )}
      {items.map((item) => (
        <SinglePane
          key={item.symbol}
          item={item}
          chartHeight={chartHeight}
          activeOverlays={activeOverlays}
          onChartReady={handleChartReady}
          globalRange={globalRange}
        />
      ))}
    </div>
  );
};

export default StackCandleStickChart;
