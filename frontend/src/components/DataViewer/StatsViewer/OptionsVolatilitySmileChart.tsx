/**
 * OptionsVolatilitySmileChart — SVG-based volatility smile visualisation with volume bars.
 *
 * Plots option cost (last traded price) against strike price for call and put
 * contracts.  An expiry selector lets the user switch between available
 * expiration dates. Call cost is drawn as a dashed blue line; put cost as a
 * solid orange line.
 *
 * Below the cost chart, a bar chart displays trading volume for calls and puts
 * at each strike price, aligned to the same x-axis.
 *
 * Data is supplied via the `vol_smile` field of `CalculateOptionStatsOutput`
 * serialised by the backend.
 */

import React, { useMemo, useRef, useState, useEffect } from 'react';
import { Select, Typography } from 'antd';
import {
  COLOR_CHART_AXIS,
  COLOR_CHART_BG,
  COLOR_CHART_CALL_IV,
  COLOR_CHART_GRID,
  COLOR_CHART_PUT_IV,
  COLOR_CHART_TOOLTIP_BG,
  COLOR_HOVER_CROSSHAIR,
} from '../../../constants/styleColors';

const { Text } = Typography;

// ─── Types (mirror backend Pydantic models) ────────────────────────────────

export interface VolSmilePoint {
  strike: number;
  call_iv: number | null;      // Implied volatility % for call
  put_iv: number | null;       // Implied volatility % for put
  call_cost: number | null;    // Option premium/cost for call
  put_cost: number | null;     // Option premium/cost for put
  call_volume: number | null;  // Trading volume for call
  put_volume: number | null;   // Trading volume for put
}

export interface VolSmileExpiry {
  expiry_date: string;  // ISO date "2026-06-01"
  points: VolSmilePoint[];
}

// ─── Constants ────────────────────────────────────────────────────────────

const PAD = { top: 24, right: 48, bottom: 44, left: 64 };
const VOL_BAR_HEIGHT = 80;  // Height allocated for volume bar chart
const VOL_GAP = 24;         // Gap between smile chart and volume chart
const TICK_COUNT_Y = 5;
const TICK_COUNT_X = 7;   // max x-axis labels

// ─── Helper ───────────────────────────────────────────────────────────────

function niceRange(min: number, max: number, ticks: number): { lo: number; hi: number; step: number } {
  const raw = (max - min) / ticks;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = Math.ceil(raw / mag) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  return { lo, hi, step };
}

// ─── Chart ────────────────────────────────────────────────────────────────

interface ChartProps {
  expiry: VolSmileExpiry;
  width: number;
  height: number;
}

const SmileChart: React.FC<ChartProps> = ({ expiry, width, height }) => {
  const cw = width - PAD.left - PAD.right;
  const ch = height - PAD.top - PAD.bottom - VOL_BAR_HEIGHT - VOL_GAP;

  const callPoints = expiry.points.filter((p) => p.call_cost !== null) as (VolSmilePoint & { call_cost: number })[];
  const putPoints  = expiry.points.filter((p) => p.put_cost  !== null) as (VolSmilePoint & { put_cost:  number })[];

  const allCosts  = [...callPoints.map((p) => p.call_cost), ...putPoints.map((p) => p.put_cost)];
  const strikes = expiry.points.map((p) => p.strike);

  // Volume data
  const callVolumes = expiry.points.filter((p) => p.call_volume !== null) as (VolSmilePoint & { call_volume: number })[];
  const putVolumes  = expiry.points.filter((p) => p.put_volume  !== null) as (VolSmilePoint & { put_volume:  number })[];
  const allVolumes = [
    ...callVolumes.map((p) => p.call_volume),
    ...putVolumes.map((p) => p.put_volume),
  ].filter((v): v is number => v !== null);
  const maxVolume = allVolumes.length > 0 ? Math.max(...allVolumes) : 0;

  const [hoverInfo, setHoverInfo] = useState<{ x: number; y: number; strike: number; callCost: number | null; putCost: number | null; callVolume: number | null; putVolume: number | null } | null>(null);

  if (strikes.length === 0 || allCosts.length === 0) {
    return (
      <Text type="secondary" style={{ padding: 24, display: 'block', textAlign: 'center' }}>
        No option cost data for this expiry.
      </Text>
    );
  }

  const minStrike = Math.min(...strikes);
  const maxStrike = Math.max(...strikes);
  const minCost   = Math.min(...allCosts);
  const maxCost   = Math.max(...allCosts);

  const xRange = niceRange(minStrike, maxStrike, TICK_COUNT_X);
  const yRange = niceRange(Math.max(0, minCost - 2), maxCost + 2, TICK_COUNT_Y);

  const xScale = (s: number) => PAD.left + ((s - xRange.lo) / (xRange.hi - xRange.lo)) * cw;
  const yScale = (v: number) => PAD.top  + (1 - (v - yRange.lo) / (yRange.hi - yRange.lo)) * ch;

  // x-axis ticks
  const xTicks: number[] = [];
  for (let t = xRange.lo; t <= xRange.hi + xRange.step * 0.01; t += xRange.step) xTicks.push(t);
  // y-axis ticks
  const yTicks: number[] = [];
  for (let t = yRange.lo; t <= yRange.hi + yRange.step * 0.01; t += yRange.step) yTicks.push(t);

  const polylinePoints = (pts: { strike: number; cost: number }[]) =>
    pts.map((p) => `${xScale(p.strike).toFixed(1)},${yScale(p.cost).toFixed(1)}`).join(' ');

  const callLine = polylinePoints(callPoints.map((p) => ({ strike: p.strike, cost: p.call_cost })));
  const putLine  = polylinePoints(putPoints.map((p) => ({ strike: p.strike, cost: p.put_cost })));

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left - PAD.left;
    const ratio = Math.max(0, Math.min(1, mx / cw));
    const hoverStrike = xRange.lo + ratio * (xRange.hi - xRange.lo);
    // find nearest point
    let nearest: VolSmilePoint | null = null;
    let minDist = Infinity;
    for (const p of expiry.points) {
      const d = Math.abs(p.strike - hoverStrike);
      if (d < minDist) { minDist = d; nearest = p; }
    }
    if (nearest) {
      setHoverInfo({
        x: xScale(nearest.strike),
        y: nearest.call_cost != null ? yScale(nearest.call_cost) : nearest.put_cost != null ? yScale(nearest.put_cost) : PAD.top,
        strike: nearest.strike,
        callCost: nearest.call_cost,
        putCost:  nearest.put_cost,
        callVolume: nearest.call_volume,
        putVolume:  nearest.put_volume,
      });
    }
  };

  return (
    <svg
      width={width}
      height={height}
      style={{ display: 'block', background: COLOR_CHART_BG, borderRadius: 6, cursor: 'crosshair' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setHoverInfo(null)}
    >
      {/* Y gridlines */}
      {yTicks.map((t) => (
        <line key={`yg${t}`} x1={PAD.left} y1={yScale(t)} x2={PAD.left + cw} y2={yScale(t)} stroke={COLOR_CHART_GRID} strokeWidth={1} />
      ))}
      {/* X gridlines */}
      {xTicks.map((t) => (
        <line key={`xg${t}`} x1={xScale(t)} y1={PAD.top} x2={xScale(t)} y2={PAD.top + ch} stroke={COLOR_CHART_GRID} strokeWidth={1} />
      ))}

      {/* Y axis labels */}
      {yTicks.map((t) => (
        <text key={`yl${t}`} x={PAD.left - 8} y={yScale(t) + 4} textAnchor="end" fill={COLOR_CHART_AXIS} fontSize={11}>{t.toFixed(1)}</text>
      ))}
      {/* Y axis title */}
      <text x={14} y={PAD.top + ch / 2} textAnchor="middle" fill={COLOR_CHART_AXIS} fontSize={11}
        transform={`rotate(-90, 14, ${PAD.top + ch / 2})`}>Option Cost ($)</text>

      {/* X axis labels */}
      {xTicks.map((t) => (
        <text key={`xl${t}`} x={xScale(t)} y={PAD.top + ch + 18} textAnchor="middle" fill={COLOR_CHART_AXIS} fontSize={11}>{t}</text>
      ))}
      {/* X axis title */}
      <text x={PAD.left + cw / 2} y={height - 4} textAnchor="middle" fill={COLOR_CHART_AXIS} fontSize={11}>Strike</text>

      {/* Axes */}
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + ch} stroke={COLOR_CHART_AXIS} strokeWidth={1} />
      <line x1={PAD.left} y1={PAD.top + ch} x2={PAD.left + cw} y2={PAD.top + ch} stroke={COLOR_CHART_AXIS} strokeWidth={1} />

      {/* Put line */}
      {putLine && (
        <polyline points={putLine} fill="none" stroke={COLOR_CHART_PUT_IV} strokeWidth={2} />
      )}
      {/* Call line (dashed) */}
      {callLine && (
        <polyline points={callLine} fill="none" stroke={COLOR_CHART_CALL_IV} strokeWidth={2} strokeDasharray="5 3" />
      )}

      {/* Put data points */}
      {putPoints.map((p) => (
        <circle key={`pd${p.strike}`} cx={xScale(p.strike)} cy={yScale(p.put_cost)} r={3} fill={COLOR_CHART_PUT_IV} />
      ))}
      {/* Call data points */}
      {callPoints.map((p) => (
        <circle key={`cd${p.strike}`} cx={xScale(p.strike)} cy={yScale(p.call_cost)} r={3} fill={COLOR_CHART_CALL_IV} />
      ))}

      {/* Volume bar chart */}
      {(() => {
        const volBaseY = PAD.top + ch + VOL_GAP;
        const volHeight = VOL_BAR_HEIGHT - 16; // leave room for axis labels
        const volScale = (v: number) => maxVolume > 0 ? (v / maxVolume) * volHeight : 0;

        return (
          <g>
            {/* Volume axis line */}
            <line x1={PAD.left} y1={volBaseY} x2={PAD.left + cw} y2={volBaseY} stroke={COLOR_CHART_AXIS} strokeWidth={1} />
            
            {/* Volume y-axis label */}
            <text x={PAD.left - 8} y={volBaseY - 4} textAnchor="end" fill={COLOR_CHART_AXIS} fontSize={10}>Volume</text>
            
            {/* Call volume bars */}
            {callVolumes.map((p) => {
              const barHeight = volScale(p.call_volume);
              const barX = xScale(p.strike) - 6;
              const barY = volBaseY - barHeight;
              return (
                <rect
                  key={`cv${p.strike}`}
                  x={barX}
                  y={barY}
                  width={6}
                  height={barHeight}
                  fill={COLOR_CHART_CALL_IV}
                  opacity={0.7}
                />
              );
            })}
            
            {/* Put volume bars */}
            {putVolumes.map((p) => {
              const barHeight = volScale(p.put_volume);
              const barX = xScale(p.strike);
              const barY = volBaseY - barHeight;
              return (
                <rect
                  key={`pv${p.strike}`}
                  x={barX}
                  y={barY}
                  width={6}
                  height={barHeight}
                  fill={COLOR_CHART_PUT_IV}
                  opacity={0.7}
                />
              );
            })}
            

          </g>
        );
      })()}

      {/* Hover crosshair */}
      {hoverInfo && (
        <>
          <line x1={hoverInfo.x} y1={PAD.top} x2={hoverInfo.x} y2={PAD.top + ch + VOL_GAP + VOL_BAR_HEIGHT} stroke={COLOR_HOVER_CROSSHAIR} strokeWidth={1} strokeDasharray="3 3" />
          {/* Tooltip box */}
          {(() => {
            const tx = hoverInfo.x + 10 > PAD.left + cw - 140 ? hoverInfo.x - 150 : hoverInfo.x + 10;
            const ty = Math.max(PAD.top, Math.min(PAD.top + ch - 86, hoverInfo.y - 40));
            return (
              <g>
                <rect x={tx} y={ty} width={140} height={86} rx={4} fill={COLOR_CHART_TOOLTIP_BG} stroke={COLOR_CHART_GRID} />
                <text x={tx + 8} y={ty + 16} fill={COLOR_CHART_AXIS} fontSize={11}>Strike: {hoverInfo.strike}</text>
                <text x={tx + 8} y={ty + 32} fill={COLOR_CHART_CALL_IV} fontSize={11}>
                  Call Cost: ${hoverInfo.callCost != null ? hoverInfo.callCost.toFixed(2) : '—'}
                </text>
                <text x={tx + 8} y={ty + 48} fill={COLOR_CHART_CALL_IV} fontSize={11}>
                  Call Vol: {hoverInfo.callVolume != null ? hoverInfo.callVolume.toLocaleString() : '—'}
                </text>
                <text x={tx + 8} y={ty + 64} fill={COLOR_CHART_PUT_IV} fontSize={11}>
                  Put Cost: ${hoverInfo.putCost != null ? hoverInfo.putCost.toFixed(2) : '—'}
                </text>
                <text x={tx + 8} y={ty + 80} fill={COLOR_CHART_PUT_IV} fontSize={11}>
                  Put Vol: {hoverInfo.putVolume != null ? hoverInfo.putVolume.toLocaleString() : '—'}
                </text>
              </g>
            );
          })()}
        </>
      )}

      {/* Legend */}
      <g transform={`translate(${PAD.left + cw - 120}, ${PAD.top + 8})`}>
        <rect x={0} y={0} width={116} height={72} rx={4} fill={COLOR_CHART_TOOLTIP_BG} stroke={COLOR_CHART_GRID} />
        <line x1={8} y1={13} x2={28} y2={13} stroke={COLOR_CHART_CALL_IV} strokeWidth={2} strokeDasharray="5 3" />
        <text x={34} y={17} fill={COLOR_CHART_CALL_IV} fontSize={11}>Call Cost</text>
        <line x1={8} y1={29} x2={28} y2={29} stroke={COLOR_CHART_PUT_IV} strokeWidth={2} />
        <text x={34} y={33} fill={COLOR_CHART_PUT_IV} fontSize={11}>Put Cost</text>
        <rect x={8} y={45} width={8} height={8} fill={COLOR_CHART_CALL_IV} opacity={0.7} />
        <text x={34} y={52} fill={COLOR_CHART_AXIS} fontSize={10}>Call Vol</text>
        <rect x={8} y={59} width={8} height={8} fill={COLOR_CHART_PUT_IV} opacity={0.7} />
        <text x={34} y={66} fill={COLOR_CHART_AXIS} fontSize={10}>Put Vol</text>
      </g>
    </svg>
  );
};

// ─── Public component ──────────────────────────────────────────────────────

interface Props {
  data: VolSmileExpiry[];
  maxHeight?: number;
}

const OptionsVolatilitySmileChart: React.FC<Props> = ({ data, maxHeight = 340 }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);

  const sortedExpiries = useMemo(
    () => [...data].sort((a, b) => a.expiry_date.localeCompare(b.expiry_date)),
    [data],
  );

  const [selectedExpiry, setSelectedExpiry] = useState<string>(sortedExpiries[0]?.expiry_date ?? '');

  // Keep selection valid when data changes.
  useEffect(() => {
    if (sortedExpiries.length && !sortedExpiries.find((e) => e.expiry_date === selectedExpiry)) {
      setSelectedExpiry(sortedExpiries[0].expiry_date);
    }
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  // Observe container width for responsiveness.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setWidth(w);
    });
    observer.observe(el);
    setWidth(el.clientWidth || 700);
    return () => observer.disconnect();
  }, []);

  const expiry = sortedExpiries.find((e) => e.expiry_date === selectedExpiry);
  const chartHeight = maxHeight - 40; // subtract selector toolbar

  if (!sortedExpiries.length) {
    return <Text type="secondary" style={{ padding: 16, display: 'block' }}>No volatility smile data.</Text>;
  }

  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      {/* Expiry selector */}
      <div style={{ paddingBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Text style={{ fontSize: 12, color: COLOR_CHART_AXIS }}>Expiry:</Text>
        <Select
          size="small"
          value={selectedExpiry}
          onChange={setSelectedExpiry}
          style={{ width: 130 }}
          options={sortedExpiries.map((e) => ({ value: e.expiry_date, label: e.expiry_date }))}
        />
        <Text style={{ fontSize: 11, color: COLOR_CHART_AXIS }}>
          {expiry ? `${expiry.points.length} strikes` : ''}
        </Text>
      </div>
      {expiry && (
        <SmileChart expiry={expiry} width={width} height={chartHeight} />
      )}
    </div>
  );
};

export default OptionsVolatilitySmileChart;
