import type { OHLCVBar } from "./types";

/** Color palette for indicator line series. */
export const INDICATOR_COLORS: Record<string, string[]> = {
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

export function indicatorColor(id: string, keyIndex: number): string {
  const palette = INDICATOR_COLORS[id] ?? ["#1677ff"];
  return palette[keyIndex % palette.length];
}

// All candidate ranges ordered smallest → largest. 0 = "All".
export const RANGE_CANDIDATES: { label: string; days: number }[] = [
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
 * Only includes ranges ≤ the data span (10% buffer for weekends/holidays).
 * Always appends "All".
 */
export function deriveRangeOptions(bars: OHLCVBar[]): { label: string; days: number }[] {
  const span = barSpanDays(bars);
  if (span === 0) return [];
  const opts = RANGE_CANDIDATES.filter((c) => c.days === 0 || c.days <= span * 1.1);
  if (!opts.some((c) => c.days === 0)) opts.push({ label: "All", days: 0 });
  return opts;
}

/** Keep bars whose date falls within the last `days` calendar days of the dataset. */
export function filterByDays(bars: OHLCVBar[], days: number): OHLCVBar[] {
  if (days === 0) return bars;
  const latestMs = Date.parse(bars[bars.length - 1].date);
  const cutoffMs  = latestMs - days * 86_400_000;
  return bars.filter((b) => Date.parse(b.date) >= cutoffMs);
}

/** Human-readable bar interval label derived from task key. */
export function intervalLabel(taskKey: string): string {
  if (taskKey.includes("ohlcv.15min")) return "15-min";
  if (taskKey.includes("ohlcv.1h"))    return "1-hour";
  if (taskKey.includes("ohlcv.1day"))  return "Daily";
  if (taskKey.includes("ohlcv.1mo"))   return "Monthly";
  const withoutSuffix = taskKey.replace(/\.(quant|text)$/, "");
  const segment = withoutSuffix.split(".").pop() ?? taskKey;
  return segment.replace(/_/g, " ");
}

/**
 * Extract granularity from `market_data_collector.ohlcv.<granularity>.quant`.
 * Returns null for non-primary OHLCV task keys.
 */
export function extractGranularity(taskKey: string): string | null {
  const m = taskKey.match(/\.ohlcv\.([^.]+)\.quant$/);
  return m ? m[1] : null;
}

/**
 * Normalise an ISO date/datetime string to either "YYYY-MM-DD" (for daily+)
 * or a Unix timestamp (seconds) for intraday bars.
 */
export function toChartTime(dateStr: string): number | string {
  if (dateStr.includes("T") || (dateStr.includes(" ") && dateStr.length > 10)) {
    const ms = Date.parse(dateStr);
    if (!Number.isNaN(ms)) return Math.floor(ms / 1000);
  }
  return dateStr.slice(0, 10);
}
