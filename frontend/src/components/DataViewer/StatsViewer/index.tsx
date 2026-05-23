/**
 * StatsViewer — renders stats task output with a dropdown to select the active view type.
 *
 * Supports the stats_view_types defined in fin_agents.stats_view_types:
 *   DataFrame        → antd Table (StatsDataFrame)
 *   CandleStick      → OHLCV candlestick chart (CandleStickChart)
 *   StackCandleStick → stacked candlestick charts (StackCandleStickChart)
 *   LineChart        → close-price line chart with volume & overlays (LineChart)
 *   BarChart         → volume bar / histogram (lightweight-charts)
 *   PieChart         → not supported for time-series data; shows DataFrame fallback
 *
 * The dropdown is populated from `statsViews` — the ordered list supplied by
 * the backend task (e.g. ["DataFrame", "CandleStick"]).
 */

import React, { useEffect, useRef } from 'react';
import { Select } from 'antd';
import StatsDataFrame from '../StatsDataFrame';
import CandleStickChart from './CandleStickChart';
import LineChart from './LineChart';
import { createChart, HistogramSeries } from 'lightweight-charts';
import type { DfSplit } from '../StatsDataFrame';

interface Props {
  dfSplit: DfSplit;
  /** Currently selected view type — controlled by the parent's header Select. */
  activeView: string;
  maxHeight?: number;
  symbol?: string;
}

// ─── BarChart (volume histogram) ──────────────────────────────────────────────

const BarChartView: React.FC<{ dfSplit: DfSplit; maxHeight: number }> = ({ dfSplit, maxHeight }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height: maxHeight,
      layout: { background: { color: '#1a1d23' }, textColor: '#9B9EA4' },
      grid: { vertLines: { color: '#2B2F38' }, horzLines: { color: '#2B2F38' } },
      timeScale: { borderColor: '#2B2F38', timeVisible: true },
      rightPriceScale: { borderColor: '#2B2F38' },
    });

    const series = chart.addSeries(HistogramSeries, { color: '#26a69a', priceFormat: { type: 'volume' } });

    const volIdx = dfSplit.columns.indexOf('volume');
    const closeIdx = dfSplit.columns.indexOf('close');

    if (volIdx !== -1) {
      const barData = dfSplit.index
        .map((date, i) => {
          const close = closeIdx !== -1 ? (dfSplit.data[i]?.[closeIdx] ?? 0) as number : 0;
          const prevClose = closeIdx !== -1 && i > 0 ? (dfSplit.data[i - 1]?.[closeIdx] ?? 0) as number : close;
          return {
            time: date as string,
            value: (dfSplit.data[i]?.[volIdx] ?? 0) as number,
            color: close >= prevClose ? '#26a69a' : '#ef5350',
          };
        })
        .filter((d, i, arr) => i === 0 || d.time > arr[i - 1].time);
      series.setData(barData);
    }
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
  }, [dfSplit, maxHeight]);

  return <div ref={containerRef} style={{ width: '100%', height: maxHeight, borderRadius: 6, overflow: 'hidden' }} />;
};

// ─── StatsViewer ──────────────────────────────────────────────────────────────

export const LABEL_MAP: Record<string, string> = {
  DataFrame: 'Table',
  CandleStick: 'Candlestick',
  StackCandleStick: 'Stacked Candles',
  LineChart: 'Line',
  BarChart: 'Volume',
  PieChart: 'Pie',
};

/** Dropdown for selecting the active stats view type. Placed in a panel header. */
export const StatsViewSelect: React.FC<{
  statsViews: string[];
  activeView: string;
  onChange: (v: string) => void;
}> = ({ statsViews, activeView, onChange }) => (
  <span
    onMouseDown={(e) => e.stopPropagation()}
    onClick={(e) => e.stopPropagation()}
    style={{ display: 'inline-block' }}
  >
    <Select
      size="small"
      value={activeView}
      onChange={onChange}
      options={statsViews.map((v) => ({ value: v, label: LABEL_MAP[v] ?? v }))}
      style={{ width: 130 }}
    />
  </span>
);

/** Renders the stats content for the given activeView — no dropdown included. */
const StatsViewer: React.FC<Props> = ({ dfSplit, activeView, maxHeight = 320, symbol }) => {
  switch (activeView) {
    case 'DataFrame':
      return <StatsDataFrame dfSplit={dfSplit} maxHeight={maxHeight} />;
    case 'CandleStick':
      return <CandleStickChart dfSplit={dfSplit} maxHeight={maxHeight} symbol={symbol} />;
    case 'LineChart':
      return <LineChart dfSplit={dfSplit} maxHeight={maxHeight} />;
    case 'BarChart':
      return <BarChartView dfSplit={dfSplit} maxHeight={maxHeight} />;
    default:
      return <StatsDataFrame dfSplit={dfSplit} maxHeight={maxHeight} />;
  }
};

export default StatsViewer;
