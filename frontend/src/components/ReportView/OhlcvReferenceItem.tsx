import { Alert } from "antd";
import type { TaskInfo } from "../../types";
import { CandlestickChart, type OHLCVBar } from "../CandlestickChart";

export function OhlcvReferenceItem({ task, symbol }: { task: TaskInfo; symbol: string }) {
  const output = task.output as Record<string, unknown>;

  const rawBars: unknown =
    output?.bars ?? output?.ohlcv ?? output?.data ?? (Array.isArray(output) ? output : null);
  const bars: OHLCVBar[] = Array.isArray(rawBars) ? (rawBars as OHLCVBar[]) : [];

  if (bars.length === 0) {
    return (
      <Alert
        type="warning"
        message="No OHLCV bars in task output"
        style={{ marginBottom: 12 }}
      />
    );
  }

  return (
    <CandlestickChart bars={bars} symbol={symbol} taskKey={task.task_key} height={300} />
  );
}
