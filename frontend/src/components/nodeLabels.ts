export const NODE_LABELS: Record<string, string> = {
  query_optimizer: "Query Optimizer",
  market_data_collector: "Market Data",
  decision_maker: "Decision Maker",
  perf_test_streamer: "Perf Test",
};

/**
 * Derive a human-readable label from a dot-separated task key.
 *
 * Strategy: strip the leading node segment and trailing type suffix
 * (`.quant` / `.text`), title-case the remaining middle segments,
 * and join them with " · ".
 *
 * Examples:
 *   query_optimizer.comprehend_basics.text  → "Comprehend Basics"
 *   market_data_collector.ohlcv.15min.quant → "Ohlcv · 15min"
 *   market_data_collector.web_search.company.text → "Web Search · Company"
 *   perf_test_streamer.mock_ingest          → "Mock Ingest"
 */
export function taskKeyLabel(task_key: string): string {
  const parts = task_key.split(".");
  // Keep middle segments: drop first (node) and last (type suffix) when ≥3 parts.
  const mid = parts.length >= 3 ? parts.slice(1, -1) : parts.slice(1);
  if (mid.length === 0) return task_key;
  return mid
    .map((p) => p.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(" · ");
}
