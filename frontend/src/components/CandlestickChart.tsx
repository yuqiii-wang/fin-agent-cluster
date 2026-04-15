import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode } from "lightweight-charts";
import { Flex, Select, Segmented, Spin, Tag, theme, Typography } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import type { CurrencyInfo, QuantIndicatorMeta, QuantIndicatorSeries, QuantStatPoint } from "../types";
import { fetchQuantIndicators, fetchQuantStat, fetchSymbolCurrency } from "../api";

const { Text } = Typography;

export interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  adj_close?: number | null;
}

interface Props {
  bars: OHLCVBar[];
  /** Ticker symbol, e.g. "AAPL" — used to query indicator data from the backend. */
  symbol: string;
  taskKey: string;
  height?: number;
}

// ── Color palette for indicator line series ────────────────────────────────
const INDICATOR_COLORS: Record<string, string[]> = {
  sma_20:   ["#1677ff"],
  sma_50:   ["#fa8c16"],
  sma_200:  ["#722ed1"],
  ema_12:   ["#13c2c2"],
  ema_26:   ["#eb2f96"],
  bb:       ["#8c8c8c", "#595959", "#8c8c8c"],
  sar:      ["#52c41a"],
  vwap:     ["#fadb14"],
  macd:     ["#1677ff", "#fa8c16", "#52c41a"],
  rsi_14:   ["#722ed1"],
  stoch:    ["#1677ff", "#fa8c16"],
  willr_14: ["#13c2c2"],
  cci_20:   ["#eb2f96"],
  mfi_14:   ["#52c41a"],
  roc_10:   ["#fadb14"],
  atr_14:   ["#ff4d4f"],
  natr_14:  ["#ff7875"],
  adx:      ["#262626", "#52c41a", "#ff4d4f"],
  aroon:    ["#52c41a", "#ff4d4f"],
  obv:      ["#1677ff"],
  ad:       ["#fa8c16"],
};

function indicatorColor(id: string, keyIndex: number): string {
  const palette = INDICATOR_COLORS[id] ?? ["#1677ff"];
  return palette[keyIndex % palette.length];
}

// ── Range helpers ──────────────────────────────────────────────────────────

// All candidate ranges ordered smallest → largest. 0 = "All".
const RANGE_CANDIDATES: { label: string; days: number }[] = [
  { label: "1D",  days: 1 },
  { label: "3D",  days: 3 },
  { label: "1W",  days: 7 },
  { label: "2W",  days: 14 },
  { label: "1M",  days: 30 },
  { label: "3M",  days: 90 },
  { label: "6M",  days: 180 },
  { label: "1Y",  days: 365 },
  { label: "2Y",  days: 730 },
  { label: "5Y",  days: 1825 },
  { label: "10Y", days: 3650 },
  { label: "All", days: 0 },
];

/** Calendar days between first and last bar. */
function barSpanDays(bars: OHLCVBar[]): number {
  if (bars.length < 2) return 0;
  return Math.max(1, Math.round(
    (Date.parse(bars[bars.length - 1].date) - Date.parse(bars[0].date)) / 86_400_000,
  ));
}

/**
 * Derive selectable time-range options from the actual data span.
 * Only includes ranges ≤ the data span (10 % buffer for weekends/holidays).
 * Always appends "All".
 */
function deriveRangeOptions(bars: OHLCVBar[]): { label: string; days: number }[] {
  const span = barSpanDays(bars);
  if (span === 0) return [];
  const opts = RANGE_CANDIDATES.filter((c) => c.days === 0 || c.days <= span * 1.1);
  if (!opts.some((c) => c.days === 0)) opts.push({ label: "All", days: 0 });
  return opts;
}

/** Keep bars whose date falls within the last `days` calendar days of the dataset. */
function filterByDays(bars: OHLCVBar[], days: number): OHLCVBar[] {
  if (days === 0) return bars;
  const latestMs = Date.parse(bars[bars.length - 1].date);
  const cutoffMs  = latestMs - days * 86_400_000;
  return bars.filter((b) => Date.parse(b.date) >= cutoffMs);
}

/** Human-readable bar interval label derived from task key. */
function intervalLabel(taskKey: string): string {
  if (taskKey.includes("ohlcv.15min")) return "15-min";
  if (taskKey.includes("ohlcv.1h"))    return "1-hour";
  if (taskKey.includes("ohlcv.1day"))  return "Daily";
  if (taskKey.includes("ohlcv.1mo"))   return "Monthly";
  const withoutSuffix = taskKey.replace(/\.(quant|text)$/, "");
  const segment = withoutSuffix.split(".").pop() ?? taskKey;
  return segment.replace(/_/g, " ");
}

/**
 * Extract granularity from ``market_data_collector.ohlcv.<granularity>.quant``.
 * Returns null for non-primary OHLCV task keys (peers, indexes, macro).
 */
function extractGranularity(taskKey: string): string | null {
  const m = taskKey.match(/\.ohlcv\.([^.]+)\.quant$/);
  return m ? m[1] : null;
}

/**
 * Normalise an ISO date/datetime string to either "YYYY-MM-DD" (for daily+)
 * or a Unix timestamp (seconds) for intraday bars, as required by lightweight-charts.
 */
function toChartTime(dateStr: string): number | string {
  if (dateStr.includes("T") || (dateStr.includes(" ") && dateStr.length > 10)) {
    const ms = Date.parse(dateStr);
    if (!Number.isNaN(ms)) return Math.floor(ms / 1000);
  }
  return dateStr.slice(0, 10);
}

// ── Indicator state ────────────────────────────────────────────────────────

type IndicatorStatus = "idle" | "loading" | "done" | "error";

interface IndicatorState {
  status: IndicatorStatus;
  series: QuantIndicatorSeries | null;
  error?: string;
}

// ── Panel chart for non-overlay indicators ─────────────────────────────────

function PanelChart({
  indicatorId,
  data,
  meta,
  height = 110,
}: {
  indicatorId: string;
  data: QuantStatPoint[];
  meta: QuantIndicatorMeta;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { token } = theme.useToken();

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      height,
      layout: {
        background: { type: ColorType.Solid, color: token.colorBgContainer },
        textColor: token.colorText,
      },
      grid: {
        vertLines: { color: token.colorBorderSecondary },
        horzLines: { color: token.colorBorderSecondary },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: token.colorBorder },
      timeScale: { borderColor: token.colorBorder, timeVisible: true, secondsVisible: false },
    });

    meta.keys.forEach((key, i) => {
      const s = chart.addSeries(LineSeries, { color: indicatorColor(indicatorId, i), lineWidth: 1 });
      const pts = data
        .map((p) => ({ time: toChartTime(p.date) as string & number, value: p.values[key] }))
        .filter((pt): pt is { time: string & number; value: number } => pt.value != null);
      s.setData(pts);
    });

    chart.timeScale().fitContent();
    return () => { chart.remove(); };
  }, [data, meta, indicatorId, height, token]);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}

// ── Main CandlestickChart ──────────────────────────────────────────────────

export function CandlestickChart({ bars, symbol, taskKey, height = 340 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { token } = theme.useToken();

  // Granularity is only derivable for primary OHLCV task keys.
  const granularity = extractGranularity(taskKey);
  const canShowIndicators = !!granularity && !!symbol;

  // Sort once ascending by date
  const sortedBars = useMemo(
    () => [...bars].sort((a, b) => Date.parse(a.date) - Date.parse(b.date)),
    [bars],
  );

  const rangeOptions = useMemo(() => deriveRangeOptions(sortedBars), [sortedBars]);
  const [selectedDays, setSelectedDays] = useState<number>(0);
  const filteredBars = useMemo(
    () => filterByDays(sortedBars, selectedDays),
    [sortedBars, selectedDays],
  );

  // ── Indicator metadata (loaded once) ──────────────────────────────────────
  const [indicatorMeta, setIndicatorMeta] = useState<QuantIndicatorMeta[]>([]);
  useEffect(() => {
    if (!canShowIndicators) return;
    fetchQuantIndicators().then(setIndicatorMeta).catch(() => {/* silent */});
  }, [canShowIndicators]);

  // ── Currency info (loaded once per symbol) ────────────────────────────────
  const [currencyInfo, setCurrencyInfo] = useState<CurrencyInfo | null>(null);
  useEffect(() => {
    if (!symbol) return;
    fetchSymbolCurrency(symbol).then(setCurrencyInfo).catch(() => {/* silent */});
  }, [symbol]);

  // ── Selected indicator ids (default: sma_20) ──────────────────────────────
  const [selectedIds, setSelectedIds] = useState<string[]>(["sma_20"]);

  // ── Per-indicator fetch state ─────────────────────────────────────────────
  const [indicatorData, setIndicatorData] = useState<Record<string, IndicatorState>>({});

  // Fetch any newly-selected indicator that hasn't been loaded yet.
  useEffect(() => {
    if (!canShowIndicators) return;
    selectedIds.forEach((id) => {
      if (indicatorData[id]) return;
      setIndicatorData((prev) => ({ ...prev, [id]: { status: "loading", series: null } }));
      fetchQuantStat(symbol, granularity!, id)
        .then((series) =>
          setIndicatorData((prev) => ({ ...prev, [id]: { status: "done", series } }))
        )
        .catch((err) =>
          setIndicatorData((prev) => ({
            ...prev,
            [id]: { status: "error", series: null, error: String(err) },
          }))
        );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, symbol, granularity, canShowIndicators]);

  // Overlay indicators: selected, loaded, overlay=true.
  const overlayIndicators = useMemo(() =>
    selectedIds
      .map((id) => indicatorData[id])
      .filter(
        (s): s is IndicatorState & { series: QuantIndicatorSeries } =>
          s?.status === "done" && s.series !== null && (s.series.meta.overlay ?? false),
      ),
    [selectedIds, indicatorData],
  );

  // Panel indicators: selected, loaded, overlay=false.
  const panelIndicators = useMemo(() =>
    selectedIds
      .map((id) => indicatorData[id])
      .filter(
        (s): s is IndicatorState & { series: QuantIndicatorSeries } =>
          s?.status === "done" && s.series !== null && !(s.series.meta.overlay ?? false),
      ),
    [selectedIds, indicatorData],
  );

  // ── Main chart ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || filteredBars.length === 0) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      height,
      layout: {
        background: { type: ColorType.Solid, color: token.colorBgContainer },
        textColor: token.colorText,
      },
      grid: {
        vertLines: { color: token.colorBorderSecondary },
        horzLines: { color: token.colorBorderSecondary },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: token.colorBorder },
      timeScale: { borderColor: token.colorBorder, timeVisible: true, secondsVisible: false },
    });

    // Candlestick
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor:         token.colorSuccess,
      downColor:       token.colorError,
      borderUpColor:   token.colorSuccess,
      borderDownColor: token.colorError,
      wickUpColor:     token.colorSuccess,
      wickDownColor:   token.colorError,
    });
    candleSeries.setData(
      filteredBars.map((bar) => ({
        time:  toChartTime(bar.date) as string & number,
        open:  bar.open,
        high:  bar.high,
        low:   bar.low,
        close: bar.close,
      })),
    );

    // Volume
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color:        token.colorPrimary,
      priceFormat:  { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeries.setData(
      filteredBars.map((bar) => ({
        time:  toChartTime(bar.date) as string & number,
        value: bar.volume,
        color: bar.close >= bar.open
          ? token.colorSuccess + "88"
          : token.colorError   + "88",
      })),
    );

    // Overlay indicator line series
    overlayIndicators.forEach(({ series }) => {
      series.meta.keys.forEach((key, i) => {
        const ls = chart.addSeries(LineSeries, {
          color: indicatorColor(series.indicator, i),
          lineWidth: 1,
          // Dashed style for BB upper/lower bands
          ...(series.indicator === "bb" && (key === "upper" || key === "lower")
            ? { lineStyle: 2 }
            : {}),
        });
        const pts = series.data
          .map((p) => ({ time: toChartTime(p.date) as string & number, value: p.values[key] }))
          .filter((pt): pt is { time: string & number; value: number } => pt.value != null);
        ls.setData(pts);
      });
    });

    chart.timeScale().fitContent();
    return () => { chart.remove(); };
  }, [filteredBars, height, token, overlayIndicators]);

  // ── Dropdown grouped options ───────────────────────────────────────────────
  const selectOptions = useMemo(() => {
    const groups: Record<string, QuantIndicatorMeta[]> = {};
    indicatorMeta.forEach((m) => { (groups[m.group] ??= []).push(m); });
    return Object.entries(groups).map(([label, items]) => ({
      label,
      options: items.map((m) => ({ label: m.label, value: m.id })),
    }));
  }, [indicatorMeta]);

  if (bars.length === 0) {
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        No OHLCV bars in output.
      </Text>
    );
  }

  const loadingIds = selectedIds.filter((id) => indicatorData[id]?.status === "loading");

  return (
    <Flex vertical gap={8}>
      {/* Header: info + range selector */}
      <Flex align="center" justify="space-between">
        <Flex align="center" gap={6}>
          <Text strong style={{ fontSize: 12 }}>
            {symbol || "—"}
          </Text>
          {currencyInfo && (
            <Tag color="blue" style={{ fontSize: 11, margin: 0 }}>
              {currencyInfo.symbol} {currencyInfo.code}
            </Tag>
          )}
          <Text type="secondary" style={{ fontSize: 11 }}>
            {intervalLabel(taskKey)}&nbsp;
            ({filteredBars.length}{filteredBars.length !== bars.length ? ` / ${bars.length}` : ""} bars)
          </Text>
        </Flex>
        {rangeOptions.length > 1 && (
          <Segmented
            size="small"
            options={rangeOptions.map((r) => ({ label: r.label, value: r.days }))}
            value={selectedDays}
            onChange={(v) => setSelectedDays(v as number)}
          />
        )}
      </Flex>

      {/* Main price chart */}
      <div ref={containerRef} style={{ width: "100%", height }} />

      {/* Indicator selector — only for primary OHLCV tasks */}
      {canShowIndicators && (
        <Flex align="center" gap={8} wrap="wrap">
          <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }}>Indicators</Text>
          <Select
            mode="multiple"
            size="small"
            style={{ flex: 1, minWidth: 200 }}
            placeholder="Add indicator…"
            value={selectedIds}
            onChange={setSelectedIds}
            options={selectOptions}
            maxTagCount="responsive"
            allowClear
          />
          {loadingIds.length > 0 && <Spin size="small" />}
        </Flex>
      )}

      {/* Missing-data warnings */}
      {canShowIndicators && selectedIds.some((id) => indicatorData[id]?.series?.all_null) && (
        <Flex wrap="wrap" gap={4}>
          {selectedIds
            .filter((id) => indicatorData[id]?.series?.all_null)
            .map((id) => {
              const meta = indicatorMeta.find((m) => m.id === id);
              return (
                <Tag key={id} icon={<InfoCircleOutlined />} color="warning">
                  {meta?.label ?? id}: missing data
                </Tag>
              );
            })}
        </Flex>
      )}

      {/* Panel indicator charts (non-overlay) */}
      {panelIndicators.map(({ series }) => (
        <Flex key={series.indicator} vertical gap={2}>
          <Flex gap={12}>
            {series.meta.keys.map((k, i) => (
              <Text key={k} style={{ fontSize: 11, color: indicatorColor(series.indicator, i) }}>
                {series.meta.label}{series.meta.keys.length > 1 ? ` (${k})` : ""}
              </Text>
            ))}
          </Flex>
          {series.all_null ? (
            <Text type="warning" style={{ fontSize: 11 }}>
              <InfoCircleOutlined /> Missing data
            </Text>
          ) : (
            <PanelChart
              indicatorId={series.indicator}
              data={series.data}
              meta={series.meta}
            />
          )}
        </Flex>
      ))}
    </Flex>
  );
}
