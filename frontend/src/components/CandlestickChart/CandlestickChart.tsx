import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode } from "lightweight-charts";
import { Flex, Select, Segmented, Spin, Tag, theme, Typography } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import type { CurrencyInfo, QuantIndicatorMeta, QuantIndicatorSeries } from "../../types";
import { fetchQuantIndicators, fetchQuantStat, fetchSymbolCurrency } from "../../api";
import type { CandlestickChartProps, IndicatorState } from "./types";
import {
  deriveRangeOptions,
  extractGranularity,
  filterByDays,
  indicatorColor,
  intervalLabel,
  toChartTime,
} from "./chartHelpers";
import { PanelChart } from "./PanelChart";

const { Text } = Typography;

export function CandlestickChart({ bars, symbol, taskKey, height = 340 }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { token } = theme.useToken();

  const granularity = extractGranularity(taskKey);
  const canShowIndicators = !!granularity && !!symbol;

  const sortedBars = useMemo(() => {
    const sorted = [...bars].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
    const seen = new Map<string | number, typeof bars[0]>();
    for (const bar of sorted) seen.set(toChartTime(bar.date), bar);
    return Array.from(seen.values());
  }, [bars]);

  const rangeOptions = useMemo(() => deriveRangeOptions(sortedBars), [sortedBars]);
  const [selectedDays, setSelectedDays] = useState<number>(0);
  const filteredBars = useMemo(
    () => filterByDays(sortedBars, selectedDays),
    [sortedBars, selectedDays],
  );

  const [indicatorMeta, setIndicatorMeta] = useState<QuantIndicatorMeta[]>([]);
  useEffect(() => {
    if (!canShowIndicators) return;
    fetchQuantIndicators().then(setIndicatorMeta).catch(() => {/* silent */});
  }, [canShowIndicators]);

  const [currencyInfo, setCurrencyInfo] = useState<CurrencyInfo | null>(null);
  useEffect(() => {
    if (!symbol) return;
    fetchSymbolCurrency(symbol).then(setCurrencyInfo).catch(() => {/* silent */});
  }, [symbol]);

  const [selectedIds, setSelectedIds] = useState<string[]>(["sma_20"]);
  const [indicatorData, setIndicatorData] = useState<Record<string, IndicatorState>>({});

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

  const overlayIndicators = useMemo(() =>
    selectedIds
      .map((id) => indicatorData[id])
      .filter(
        (s): s is IndicatorState & { series: QuantIndicatorSeries } =>
          s?.status === "done" && s.series !== null && (s.series.meta.overlay ?? false),
      ),
    [selectedIds, indicatorData],
  );

  const panelIndicators = useMemo(() =>
    selectedIds
      .map((id) => indicatorData[id])
      .filter(
        (s): s is IndicatorState & { series: QuantIndicatorSeries } =>
          s?.status === "done" && s.series !== null && !(s.series.meta.overlay ?? false),
      ),
    [selectedIds, indicatorData],
  );

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

    overlayIndicators.forEach(({ series }) => {
      series.meta.keys.forEach((key, i) => {
        const ls = chart.addSeries(LineSeries, {
          color: indicatorColor(series.indicator, i),
          lineWidth: 1,
          ...(series.indicator === "bb" && (key === "upper" || key === "lower")
            ? { lineStyle: 2 }
            : {}),
        });
        const seen = new Map<string | number, { time: string & number; value: number }>();
        for (const p of series.data) {
          const value = p.values[key];
          if (value != null) seen.set(toChartTime(p.date), { time: toChartTime(p.date) as string & number, value });
        }
        ls.setData(Array.from(seen.values()));
      });
    });

    chart.timeScale().fitContent();
    return () => { chart.remove(); };
  }, [filteredBars, height, token, overlayIndicators]);

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
      <Flex align="center" justify="space-between">
        <Flex align="center" gap={6}>
          <Text strong style={{ fontSize: 12 }}>{symbol || "—"}</Text>
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

      <div ref={containerRef} style={{ width: "100%", height }} />

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
