import { useEffect, useRef } from "react";
import { createChart, ISeriesApi, CandlestickData, Time, CandlestickSeries } from "lightweight-charts";
import { theme } from "antd";

interface Props {
  bars: any[];
}

export function CandlestickOutput({ bars }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const { token } = theme.useToken();

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 300,
      layout: {
        background: { color: 'transparent' },
        textColor: token.colorTextSecondary,
      },
      grid: {
        vertLines: { color: token.colorBorderSecondary },
        horzLines: { color: token.colorBorderSecondary },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    candlestickSeriesRef.current = candlestickSeries;

    const formattedData: CandlestickData[] = bars.map(bar => ({
      time: (typeof bar.time === 'string' ? new Date(bar.time).getTime() / 1000 : bar.time) as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    
    // remove duplicates and sort by time
    const deduplicatedData = Array.from(new Map(formattedData.map(item => [item.time, item])).values())
        .sort((a, b) => (Number(a.time) - Number(b.time)));

    candlestickSeries.setData(deduplicatedData);

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [bars, token]);

  return <div ref={chartContainerRef} style={{ width: "100%", height: "300px" }} />;
}
