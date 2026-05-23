/**
 * CandleStickChart — renders OHLCV data as a candlestick chart using lightweight-charts v5.
 *
 * Layout (bottom-up):
 *   Volume histogram — bottom 20 %
 *   RSI 14 line      — next 20 % (when enabled)
 *   OHLC candles + SMA 20 overlay — remainder
 *
 * Overlay toggles (SMA 20 / RSI 14) are rendered above the chart and are only
 * shown when the corresponding column is present in dfSplit.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Select } from 'antd';
import { createChart, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts';
import type { DfSplit } from '../StatsDataFrame';

type Overlay = 'sma_20' | 'rsi_14';

const OVERLAY_COLOR: Record<Overlay, string> = {
  sma_20: '#f4c430',
  rsi_14: '#a78bfa',
};

const OVERLAY_LABEL: Record<Overlay, string> = {
  sma_20: 'SMA 20',
  rsi_14: 'RSI 14',
};

interface Props {
  dfSplit: DfSplit;
  maxHeight?: number;
  symbol?: string;
}

const TOOLBAR_H = 32;

const CandleStickChart: React.FC<Props> = ({ dfSplit, maxHeight = 320, symbol }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const availableOverlays = (['sma_20', 'rsi_14'] as Overlay[]).filter((o) =>
    dfSplit.columns.includes(o),
  );

  const [activeOverlays, setActiveOverlays] = useState<Set<Overlay>>(new Set());

  const chartHeight = availableOverlays.length > 0 ? maxHeight - TOOLBAR_H : maxHeight;
  const rsiActive = activeOverlays.has('rsi_14');

  // OHLC bottom margin expands when RSI is shown to make room for the RSI pane.
  const ohlcBottom = rsiActive ? 0.44 : 0.25;

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: chartHeight,
      layout: {
        background: { color: '#1a1d23' },
        textColor: '#9B9EA4',
      },
      grid: {
        vertLines: { color: '#2B2F38' },
        horzLines: { color: '#2B2F38' },
      },
      timeScale: {
        borderColor: '#2B2F38',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#2B2F38',
        scaleMargins: { top: 0.05, bottom: ohlcBottom },
      },
    });

    const { index, columns, data } = dfSplit;
    const openIdx   = columns.indexOf('open');
    const highIdx   = columns.indexOf('high');
    const lowIdx    = columns.indexOf('low');
    const closeIdx  = columns.indexOf('close');
    const volumeIdx = columns.indexOf('volume');
    const smaIdx    = columns.indexOf('sma_20');
    const rsiIdx    = columns.indexOf('rsi_14');

    if (openIdx === -1 || highIdx === -1 || lowIdx === -1 || closeIdx === -1) {
      chart.remove();
      return;
    }

    const sorted = index
      .map((date, i) => ({
        time:   date as string,
        open:   (data[i]?.[openIdx]   ?? 0) as number,
        high:   (data[i]?.[highIdx]   ?? 0) as number,
        low:    (data[i]?.[lowIdx]    ?? 0) as number,
        close:  (data[i]?.[closeIdx]  ?? 0) as number,
        volume: volumeIdx !== -1 ? ((data[i]?.[volumeIdx] ?? 0) as number) : 0,
        sma20:  smaIdx   !== -1 ? ((data[i]?.[smaIdx]    ?? null) as number | null) : null,
        rsi14:  rsiIdx   !== -1 ? ((data[i]?.[rsiIdx]    ?? null) as number | null) : null,
      }))
      .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
      .filter((d, i, arr) => i === 0 || d.time !== arr[i - 1].time);

    // ── Candlestick ──────────────────────────────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });
    candleSeries.setData(
      sorted.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
    );

    // ── SMA 20 overlay ───────────────────────────────────────────────────────
    if (activeOverlays.has('sma_20') && smaIdx !== -1) {
      const smaSeries = chart.addSeries(LineSeries, {
        color: OVERLAY_COLOR.sma_20,
        lineWidth: 1,
        priceScaleId: 'right',
        lastValueVisible: false,
        priceLineVisible: false,
      });
      smaSeries.setData(
        sorted
          .filter((d) => d.sma20 !== null)
          .map(({ time, sma20 }) => ({ time, value: sma20 as number })),
      );
    }

    // ── Volume histogram ─────────────────────────────────────────────────────
    if (volumeIdx !== -1) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeries.setData(
        sorted.map(({ time, open, close, volume }) => ({
          time,
          value: volume,
          color: close >= open ? 'rgba(38,166,154,0.5)' : 'rgba(239,83,80,0.5)',
        })),
      );
    }

    // ── RSI 14 pane ──────────────────────────────────────────────────────────
    if (activeOverlays.has('rsi_14') && rsiIdx !== -1) {
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
        sorted
          .filter((d) => d.rsi14 !== null)
          .map(({ time, rsi14 }) => ({ time, value: rsi14 as number })),
      );
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [dfSplit, chartHeight, activeOverlays, ohlcBottom]);

  const toggleOverlay = (o: Overlay, checked: boolean) => {
    setActiveOverlays((prev) => {
      const next = new Set(prev);
      checked ? next.add(o) : next.delete(o);
      return next;
    });
  };

  if (!dfSplit.index.length) {
    return <span style={{ fontSize: 12, opacity: 0.5 }}>No data</span>;
  }

  return (
    <div>
      {symbol && (
        <span style={{ display: 'block', fontSize: 12, fontFamily: 'monospace', fontWeight: 600, color: '#e8e9ec', padding: '2px 8px' }}>
          {symbol}
        </span>
      )}
      {availableOverlays.length > 0 && (
        <div style={{ display: 'flex', gap: 8, padding: '4px 8px', height: TOOLBAR_H, alignItems: 'center' }}>
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
      <div
        ref={containerRef}
        style={{ width: '100%', height: chartHeight, borderRadius: 6, overflow: 'hidden' }}
      />
    </div>
  );
};

export default CandleStickChart;
