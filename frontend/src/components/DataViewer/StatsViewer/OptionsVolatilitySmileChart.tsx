/**
 * OptionsVolatilitySmileChart — SVG-based volatility smile visualisation.
 *
 * Plots implied volatility (IV %) against strike price for call and put
 * contracts.  An expiry selector lets the user switch between available
 * expiration dates.  Call IV is drawn as a dashed blue line; put IV as a
 * solid orange line.
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
  call_iv: number | null;
  put_iv: number | null;
}

export interface VolSmileExpiry {
  expiry_date: string;  // ISO date "2026-06-01"
  points: VolSmilePoint[];
}

// ─── Constants ────────────────────────────────────────────────────────────

const PAD = { top: 24, right: 48, bottom: 44, left: 64 };
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
  const ch = height - PAD.top - PAD.bottom;

  const callPoints = expiry.points.filter((p) => p.call_iv !== null) as (VolSmilePoint & { call_iv: number })[];
  const putPoints  = expiry.points.filter((p) => p.put_iv  !== null) as (VolSmilePoint & { put_iv:  number })[];

  const allIV  = [...callPoints.map((p) => p.call_iv), ...putPoints.map((p) => p.put_iv)];
  const strikes = expiry.points.map((p) => p.strike);

  const [hoverInfo, setHoverInfo] = useState<{ x: number; y: number; strike: number; callIv: number | null; putIv: number | null } | null>(null);

  if (strikes.length === 0 || allIV.length === 0) {
    return (
      <Text type="secondary" style={{ padding: 24, display: 'block', textAlign: 'center' }}>
        No implied volatility data for this expiry.
      </Text>
    );
  }

  const minStrike = Math.min(...strikes);
  const maxStrike = Math.max(...strikes);
  const minIV     = Math.min(...allIV);
  const maxIV     = Math.max(...allIV);

  const xRange = niceRange(minStrike, maxStrike, TICK_COUNT_X);
  const yRange = niceRange(Math.max(0, minIV - 5), maxIV + 5, TICK_COUNT_Y);

  const xScale = (s: number) => PAD.left + ((s - xRange.lo) / (xRange.hi - xRange.lo)) * cw;
  const yScale = (v: number) => PAD.top  + (1 - (v - yRange.lo) / (yRange.hi - yRange.lo)) * ch;

  // x-axis ticks
  const xTicks: number[] = [];
  for (let t = xRange.lo; t <= xRange.hi + xRange.step * 0.01; t += xRange.step) xTicks.push(t);
  // y-axis ticks
  const yTicks: number[] = [];
  for (let t = yRange.lo; t <= yRange.hi + yRange.step * 0.01; t += yRange.step) yTicks.push(t);

  const polylinePoints = (pts: { strike: number; iv: number }[]) =>
    pts.map((p) => `${xScale(p.strike).toFixed(1)},${yScale(p.iv).toFixed(1)}`).join(' ');

  const callLine = polylinePoints(callPoints.map((p) => ({ strike: p.strike, iv: p.call_iv })));
  const putLine  = polylinePoints(putPoints.map((p) => ({ strike: p.strike, iv: p.put_iv })));

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
        y: nearest.call_iv != null ? yScale(nearest.call_iv) : nearest.put_iv != null ? yScale(nearest.put_iv) : PAD.top,
        strike: nearest.strike,
        callIv: nearest.call_iv,
        putIv:  nearest.put_iv,
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
        transform={`rotate(-90, 14, ${PAD.top + ch / 2})`}>IV (%)</text>

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
        <circle key={`pd${p.strike}`} cx={xScale(p.strike)} cy={yScale(p.put_iv)} r={3} fill={COLOR_CHART_PUT_IV} />
      ))}
      {/* Call data points */}
      {callPoints.map((p) => (
        <circle key={`cd${p.strike}`} cx={xScale(p.strike)} cy={yScale(p.call_iv)} r={3} fill={COLOR_CHART_CALL_IV} />
      ))}

      {/* Hover crosshair */}
      {hoverInfo && (
        <>
          <line x1={hoverInfo.x} y1={PAD.top} x2={hoverInfo.x} y2={PAD.top + ch} stroke={COLOR_HOVER_CROSSHAIR} strokeWidth={1} strokeDasharray="3 3" />
          {/* Tooltip box */}
          {(() => {
            const tx = hoverInfo.x + 10 > PAD.left + cw - 110 ? hoverInfo.x - 120 : hoverInfo.x + 10;
            const ty = Math.max(PAD.top, Math.min(PAD.top + ch - 62, hoverInfo.y - 30));
            return (
              <g>
                <rect x={tx} y={ty} width={110} height={62} rx={4} fill={COLOR_CHART_TOOLTIP_BG} stroke={COLOR_CHART_GRID} />
                <text x={tx + 8} y={ty + 16} fill={COLOR_CHART_AXIS} fontSize={11}>Strike: {hoverInfo.strike}</text>
                <text x={tx + 8} y={ty + 32} fill={COLOR_CHART_CALL_IV} fontSize={11}>
                  Call IV: {hoverInfo.callIv != null ? `${hoverInfo.callIv.toFixed(2)}%` : '—'}
                </text>
                <text x={tx + 8} y={ty + 48} fill={COLOR_CHART_PUT_IV} fontSize={11}>
                  Put IV: {hoverInfo.putIv != null ? `${hoverInfo.putIv.toFixed(2)}%` : '—'}
                </text>
              </g>
            );
          })()}
        </>
      )}

      {/* Legend */}
      <g transform={`translate(${PAD.left + cw - 120}, ${PAD.top + 8})`}>
        <rect x={0} y={0} width={116} height={40} rx={4} fill={COLOR_CHART_TOOLTIP_BG} stroke={COLOR_CHART_GRID} />
        <line x1={8} y1={13} x2={28} y2={13} stroke={COLOR_CHART_CALL_IV} strokeWidth={2} strokeDasharray="5 3" />
        <text x={34} y={17} fill={COLOR_CHART_CALL_IV} fontSize={11}>Call IV</text>
        <line x1={8} y1={29} x2={28} y2={29} stroke={COLOR_CHART_PUT_IV} strokeWidth={2} />
        <text x={34} y={33} fill={COLOR_CHART_PUT_IV} fontSize={11}>Put IV</text>
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
