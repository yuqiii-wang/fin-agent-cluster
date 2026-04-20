import type { CurrencyInfo, QuantIndicatorMeta, QuantIndicatorSeries } from "../types";
import { BASE } from "./config";

// ── Quant ────────────────────────────────────────────────────────────────────

/** Fetch the static list of available technical indicators from the backend. */
export async function fetchQuantIndicators(): Promise<QuantIndicatorMeta[]> {
  const res = await fetch(`${BASE}/quant/indicators`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Fetch a single indicator time-series for a given symbol and granularity.
 *  One call per indicator — no bulk fetching. */
export async function fetchQuantStat(
  symbol: string,
  granularity: string,
  indicator: string,
  instrumentType = "equity",
): Promise<QuantIndicatorSeries> {
  const params = new URLSearchParams({ indicator, instrument_type: instrumentType });
  const res = await fetch(
    `${BASE}/quant/stats/${encodeURIComponent(symbol)}/${encodeURIComponent(granularity)}?${params}`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/** Fetch currency info for a symbol (ISO 4217 code, name, display symbol, decimals).
 *  Returns null when the symbol has no region/currency data in the DB. */
export async function fetchSymbolCurrency(symbol: string): Promise<CurrencyInfo | null> {
  const res = await fetch(`${BASE}/quant/symbol-currency/${encodeURIComponent(symbol)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
