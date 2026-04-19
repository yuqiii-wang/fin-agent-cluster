import { Tag } from "antd";

export const isQuantKey = (taskKey: string): boolean => taskKey.endsWith(".quant");
export const isTextKey  = (taskKey: string): boolean => taskKey.endsWith(".text");

export function taskLabel(taskKey: string): string {
  const map: Record<string, string> = {
    "market_data_collector.ohlcv.15min.quant":        "OHLCV 15-min (7 days)",
    "market_data_collector.ohlcv.1h.quant":           "OHLCV 1-hour (30 days)",
    "market_data_collector.ohlcv.1day.quant":         "OHLCV Daily (1 year)",
    "market_data_collector.ohlcv.1mo.quant":          "OHLCV Monthly (10 years)",
    "market_data_collector.ohlcv.futures_1mo.quant":  "Futures 1-month",
    "market_data_collector.ohlcv.futures_6mo.quant":  "Futures 6-month",
    "market_data_collector.ohlcv.options_1mo.quant":  "Options 1-month",
    "market_data_collector.ohlcv.options_6mo.quant":  "Options 6-month",
    "market_data_collector.us_treasury.quant":        "US Treasury Yields",
    "market_data_collector.web_search.company.text":  "Company News",
    "query_optimizer.comprehend_basics.text":         "Query Analysis",
    "query_optimizer.validate_basics.text":           "Validate Basics",
    "query_optimizer.populate_json.text":             "Populate Output",
    "decision_maker.llm_infer.text":                  "Decision Inference",
    "decision_maker.db_insert_report.text":           "Save Report",
  };
  const withoutSuffix = taskKey.replace(/\.(quant|text)$/, "");
  const segment = withoutSuffix.split(".").pop() ?? taskKey;
  return map[taskKey] ?? segment.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const ABSENT_TAG = (
  <Tag color="default" style={{ fontStyle: "italic", opacity: 0.6 }}>
    Data absent
  </Tag>
);

export function sentimentColor(level: string | undefined): string {
  if (!level) return "default";
  const l = level.toLowerCase();
  if (l === "positive" || l === "bullish") return "success";
  if (l === "negative" || l === "bearish") return "error";
  if (l === "neutral") return "default";
  return "processing";
}
