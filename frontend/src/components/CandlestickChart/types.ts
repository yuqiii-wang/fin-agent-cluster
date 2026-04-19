import type { QuantIndicatorSeries } from "../../types";

export interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  adj_close?: number | null;
}

export interface CandlestickChartProps {
  bars: OHLCVBar[];
  /** Ticker symbol, e.g. "AAPL" — used to query indicator data from the backend. */
  symbol: string;
  taskKey: string;
  height?: number;
}

export type IndicatorStatus = "idle" | "loading" | "done" | "error";

export interface IndicatorState {
  status: IndicatorStatus;
  series: QuantIndicatorSeries | null;
  error?: string;
}
