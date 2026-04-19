import { useEffect, useRef } from "react";
import { createChart, LineSeries, ColorType, CrosshairMode } from "lightweight-charts";
import { theme } from "antd";
import type { QuantIndicatorMeta, QuantStatPoint } from "../../types";
import { indicatorColor, toChartTime } from "./chartHelpers";

interface PanelChartProps {
  indicatorId: string;
  data: QuantStatPoint[];
  meta: QuantIndicatorMeta;
  height?: number;
}

export function PanelChart({
  indicatorId,
  data,
  meta,
  height = 110,
}: PanelChartProps) {
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
      const seen = new Map<string | number, { time: string & number; value: number }>();
      for (const p of data) {
        const value = p.values[key];
        if (value != null) seen.set(toChartTime(p.date), { time: toChartTime(p.date) as string & number, value });
      }
      s.setData(Array.from(seen.values()));
    });

    chart.timeScale().fitContent();
    return () => { chart.remove(); };
  }, [data, meta, indicatorId, height, token]);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}
