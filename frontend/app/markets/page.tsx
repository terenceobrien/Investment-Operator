'use client';

import { MouseEvent, useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { SkeletonBlock } from '@/components/Skeleton';
import { T, sx, pct, formatCurrency } from '@/lib/tokens';

const HORIZONS = ['1D', '1W', '1M', '3M', '6M', '1Y', 'YTD'];
const TICKERS  = ['SPY', 'QQQ', 'IWM', 'TLT', 'HYG', 'GLD', 'USO', 'BTC-USD'];
const TFS      = ['1D', '5D', '1M', '3M', 'YTD'];

function heatColor(ret: number | null): { bg: string; text: string } {
  if (ret === null || ret === undefined) return { bg: 'rgba(255,255,255,0.03)', text: T.textMuted };
  if (ret >  1)   return { bg: 'rgba(60,140,80,0.35)',  text: '#7bc98a' };
  if (ret >  0.3) return { bg: 'rgba(60,140,80,0.22)',  text: '#6dba7c' };
  if (ret >  0)   return { bg: 'rgba(60,140,80,0.12)',  text: '#57a06a' };
  if (ret > -0.3) return { bg: 'rgba(160,70,70,0.12)',  text: '#b85555' };
  if (ret > -1)   return { bg: 'rgba(160,70,70,0.22)',  text: '#c46060' };
  return                  { bg: 'rgba(160,70,70,0.35)',  text: '#d07070' };
}

function getTimestamp(row: any): string {
  return row.time || row.Time || row.Date || row.datetime || row.Datetime || row.index || '';
}

function formatTimeLabel(value: Date, tf: string): string {
  if (Number.isNaN(value.getTime())) return '';
  if (tf === '1D') {
    return new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(value);
  }
  if (tf === '5D') {
    const day = new Intl.DateTimeFormat('en-US', { weekday: 'short' }).format(value);
    const time = new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(value);
    return `${day} ${time}`;
  }
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  }).format(value);
}

function getEvenlySpacedIndices(length: number, target = 7): number[] {
  if (length <= 0) return [];
  const count = Math.min(target, length);
  if (count === 1) return [0];
  const step = (length - 1) / (count - 1);
  return Array.from(new Set(Array.from({ length: count }, (_, idx) => Math.round(idx * step))));
}

function formatHoverTimeLabel(value: Date, tf: string): string {
  if (Number.isNaN(value.getTime())) return '';
  if (tf === '1D') {
    const date = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(value);
    const time = new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(value);
    return `${date} · ${time}`;
  }
  if (tf === '5D') {
    const day = new Intl.DateTimeFormat('en-US', { weekday: 'short' }).format(value);
    const date = new Intl.DateTimeFormat('en-US', { month: 'numeric', day: 'numeric' }).format(value);
    const time = new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(value);
    return `${day} ${date} · ${time}`;
  }
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: '2-digit',
  }).format(value);
}

function PriceChart({ chart, ticker, tf }: { chart: any; ticker: string; tf: string }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const closes = chart.ohlcv.map((d: any) => d.Close);
  const first = closes[0];
  const last = closes[closes.length - 1];
  const change = last - first;
  const chgPct = (change / first) * 100;
  const isPos = change >= 0;
  const lineCol = isPos ? T.up : T.dn;
  const priceMin = Math.min(...closes);
  const priceMax = Math.max(...closes);
  const padding = (priceMax - priceMin) * 0.08 || 1;
  const domainMin = priceMin - padding;
  const domainMax = priceMax + padding;
  const svgWidth = 1000;
  const svgHeight = 360;
  const padLeft = 72;
  const padRight = 24;
  const padTop = 14;
  const padBottom = 16;
  const plotWidth = svgWidth - padLeft - padRight;
  const plotHeight = svgHeight - padTop - padBottom;

  const chartData = chart.ohlcv.map((d: any, idx: number) => {
    const rawTime = getTimestamp(d);
    return {
      idx,
      rawTime,
      timestamp: new Date(rawTime),
      price: Number(d.Close),
    };
  });

  const xForIndex = (idx: number) => padLeft + (idx / Math.max(chartData.length - 1, 1)) * plotWidth;
  const yForPrice = (price: number) => padTop + ((domainMax - price) / (domainMax - domainMin || 1)) * plotHeight;

  const points = chartData.map((point: any, idx: number) => {
    const x = xForIndex(idx);
    const y = yForPrice(point.price);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');

  const xLabelIndices = getEvenlySpacedIndices(chartData.length, 7);
  const xLabels = xLabelIndices.map((idx) => {
    const point = chartData[idx];
    const x = xForIndex(idx);
    return {
      key: `${point.rawTime}-${idx}`,
      x,
      label: formatTimeLabel(point.timestamp, tf),
    };
  });

  const yHairlines = Array.from({ length: 4 }, (_, idx) => {
    const ratio = idx / 3;
    const value = domainMax - ratio * (domainMax - domainMin);
    const y = padTop + ratio * plotHeight;
    return { y, value };
  });

  const hoveredPoint = hoveredIndex !== null ? chartData[hoveredIndex] : null;
  const hoveredX = hoveredIndex !== null ? xForIndex(hoveredIndex) : null;
  const hoveredY = hoveredPoint ? yForPrice(hoveredPoint.price) : null;

  const onMouseMove = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = ((event.clientX - rect.left) / rect.width) * svgWidth;
    const clampedX = Math.min(svgWidth - padRight, Math.max(padLeft, relativeX));
    const ratio = (clampedX - padLeft) / Math.max(plotWidth, 1);
    const idx = Math.round(ratio * Math.max(chartData.length - 1, 1));
    setHoveredIndex(Math.max(0, Math.min(chartData.length - 1, idx)));
  };

  return (
    <div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px,1fr))',
        borderBottom: `0.5px solid ${T.border}`,
      }}>
        {[
          { label: `${ticker} last`, val: formatCurrency(last), color: T.text },
          { label: `Change (${tf})`, val: pct(chgPct), color: isPos ? T.up : T.dn },
          { label: 'High', val: formatCurrency(priceMax), color: T.text },
          { label: 'Low', val: formatCurrency(priceMin), color: T.text },
        ].map(({ label, val, color }, i) => (
          <div key={label} style={{
            padding: '14px 24px',
            borderRight: i < 3 ? `0.5px solid ${T.border}` : 'none',
          }}>
            <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
              {label}
            </div>
            <div style={{ fontFamily: T.mono, fontSize: '20px', fontWeight: 300, letterSpacing: '-0.5px', color }}>
              {val}
            </div>
          </div>
        ))}
      </div>

      <div style={{ padding: '32px 8px 24px' }}>
        <div style={{ position: 'relative', overflow: 'visible' }}>
          <svg
            key={`${ticker}-${tf}`}
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            width="100%"
            height="360"
            role="img"
            aria-label={`${ticker} price chart`}
            style={{ overflow: 'visible', display: 'block' }}
            onMouseMove={onMouseMove}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            {yHairlines.map((line) => (
              <g key={line.y}>
                <line
                  x1={padLeft}
                  x2={svgWidth - padRight}
                  y1={line.y}
                  y2={line.y}
                  stroke="rgba(255,255,255,0.04)"
                  strokeWidth="0.5"
                  shapeRendering="crispEdges"
                />
                <text
                  x={padLeft - 8}
                  y={line.y - 2}
                  textAnchor="end"
                  style={{
                    fontFamily: T.mono,
                    fontSize: '9px',
                    fill: T.textMuted,
                  }}
                >
                  {formatCurrency(line.value)}
                </text>
              </g>
            ))}

            <polyline
              className="temper-chart-line"
              pathLength={1000}
              fill="none"
              stroke={lineCol}
              strokeWidth="1.25"
              strokeLinejoin="miter"
              strokeLinecap="square"
              points={points}
            />

            {hoveredPoint && hoveredX !== null && hoveredY !== null && (
              <g pointerEvents="none">
                <line
                  x1={hoveredX}
                  y1={padTop}
                  x2={hoveredX}
                  y2={svgHeight - padBottom}
                  stroke="rgba(255,255,255,0.24)"
                  strokeWidth="0.75"
                  strokeDasharray="3 4"
                />
                <line
                  x1={padLeft}
                  y1={hoveredY}
                  x2={svgWidth - padRight}
                  y2={hoveredY}
                  stroke="rgba(255,255,255,0.18)"
                  strokeWidth="0.75"
                  strokeDasharray="3 4"
                />
                <circle cx={hoveredX} cy={hoveredY} r="3.2" fill={T.bg} stroke={lineCol} strokeWidth="1.5" />
              </g>
            )}
          </svg>

          {hoveredPoint && hoveredX !== null && hoveredY !== null && (
            <>
              <div
                style={{
                  position: 'absolute',
                  right: '0px',
                  top: `${(hoveredY / svgHeight) * 100}%`,
                  transform: 'translateY(-50%)',
                  padding: '5px 8px',
                  background: 'rgba(7,7,10,0.94)',
                  border: `0.5px solid ${T.border}`,
                  color: lineCol,
                  fontFamily: T.mono,
                  fontSize: '10px',
                  whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.28)',
                }}
              >
                {formatCurrency(hoveredPoint.price)}
              </div>
              <div
                style={{
                  position: 'absolute',
                  left: `${(hoveredX / svgWidth) * 100}%`,
                  top: `${svgHeight - 10}px`,
                  transform: 'translate(-50%, 0)',
                  padding: '5px 8px',
                  background: 'rgba(7,7,10,0.94)',
                  border: `0.5px solid ${T.border}`,
                  color: 'rgba(255,255,255,0.82)',
                  fontFamily: T.mono,
                  fontSize: '10px',
                  whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.28)',
                }}
              >
                {formatHoverTimeLabel(hoveredPoint.timestamp, tf)}
              </div>
            </>
          )}

          <div
            style={{
              borderTop: '0.5px solid rgba(255,255,255,0.06)',
              marginTop: '2px',
              paddingTop: '8px',
              position: 'relative',
              height: '24px',
            }}
          >
            {xLabels.map((label) => (
              <span
                key={label.key}
                style={{
                  position: 'absolute',
                  left: `${(label.x / svgWidth) * 100}%`,
                  transform: 'translateX(-50%)',
                  fontFamily: T.mono,
                  fontSize: '9px',
                  color: T.textMuted,
                  whiteSpace: 'nowrap',
                }}
              >
                {label.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MarketsPage() {
  const [horizon, setHorizon] = useState('1D');
  const [ticker,  setTicker]  = useState('SPY');
  const [tf,      setTf]      = useState('1D');

  const { data: heatmap, isLoading: heatmapLoading } = useSWR(
    `/api/prices/heatmap?horizon=${horizon}`, fetcher, { refreshInterval: 300000 }
  );
  const { data: chart, isLoading: chartLoading } = useSWR(
    `/api/prices/chart?ticker=${ticker}&tf=${tf}`, fetcher, { refreshInterval: 300000 }
  );

  return (
    <main style={sx.main}>

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
          <span style={sx.sectionLabel}>Market data</span>
          <span style={sx.sectionMeta}>Price action · Sector returns · Charts</span>
        </div>
      </div>

      {/* ── Horizon selector ─────────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        borderBottom: `0.5px solid ${T.border}`,
        height: '40px',
        gap: '0',
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}>
        {HORIZONS.map((h, i) => {
          const active = horizon === h;
          return (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              style={{
                fontFamily: T.sans,
                fontSize: '12px',
                letterSpacing: '1px',
                textTransform: 'uppercase',
                color: active ? 'rgba(255,255,255,0.88)' : T.textMuted,
                background: active ? 'rgba(255,255,255,0.06)' : 'transparent',
                border: 'none',
                borderRight: `0.5px solid ${T.border}`,
                borderLeft: i === 0 ? `0.5px solid ${T.border}` : 'none',
                padding: '0 14px',
                height: '100%',
                cursor: 'pointer',
                fontWeight: active ? 500 : 400,
              }}
            >
              {h}
            </button>
          );
        })}
      </div>

      {/* ── Broad market returns ─────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Broad market returns</span>
          <span style={sx.sectionMeta}>{horizon}</span>
        </div>
        {heatmapLoading ? (
          <div style={{ padding: '16px 24px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px,1fr))', gap: '1px' }}>
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} style={{ padding: '14px 16px', background: 'rgba(255,255,255,0.02)' }}>
                  <SkeletonBlock width="58%" height={10} style={{ marginBottom: '8px' }} />
                  <SkeletonBlock width="44%" height={15} />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px,1fr))' }}>
            {heatmap?.cross?.map((item: any, i: number) => {
              const { bg, text } = heatColor(item.return);
              return (
                <div key={item.ticker} style={{
                  background: bg,
                  padding: '14px 16px',
                  borderRight: i < (heatmap.cross.length - 1) ? `0.5px solid rgba(255,255,255,0.04)` : 'none',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}>
                  <span style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.5px', color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase' }}>
                    {item.name || item.ticker}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '15px', fontWeight: 300, color: text, letterSpacing: '-0.3px' }}>
                    {item.return !== null ? pct(item.return) : '—'}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Sector returns ───────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Sector returns</span>
          <span style={sx.sectionMeta}>{horizon}</span>
        </div>
        {heatmapLoading ? (
          <div style={{ padding: '16px 24px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px,1fr))', gap: '1px' }}>
              {Array.from({ length: 11 }).map((_, i) => (
                <div key={i} style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)' }}>
                  <SkeletonBlock width="64%" height={10} style={{ marginBottom: '8px' }} />
                  <SkeletonBlock width="42%" height={15} />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px,1fr))' }}>
            {heatmap?.sectors?.map((item: any, i: number) => {
              const { bg, text } = heatColor(item.return);
              const total = heatmap.sectors.length;
              return (
                <div key={item.ticker} style={{
                  background: bg,
                  padding: '12px 16px',
                  borderRight: (i + 1) % 6 !== 0 ? `0.5px solid rgba(255,255,255,0.04)` : 'none',
                  borderBottom: i < total - 6 ? `0.5px solid rgba(255,255,255,0.04)` : 'none',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}>
                  <span style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.5px', color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase' }}>
                    {item.name || item.ticker}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '15px', fontWeight: 300, color: text, letterSpacing: '-0.3px' }}>
                    {item.return !== null ? pct(item.return) : '—'}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Price chart ──────────────────────────────────────────────────── */}
      <div>
        <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
          <span style={sx.sectionLabel}>Price chart</span>
          {/* Ticker + timeframe controls inline */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <select
              value={ticker}
              onChange={e => setTicker(e.target.value)}
              style={{
                fontFamily: T.mono,
                fontSize: '12px',
                letterSpacing: '0.5px',
                color: 'rgba(255,255,255,0.75)',
                background: 'transparent',
                border: `0.5px solid ${T.border}`,
                padding: '3px 8px',
                marginRight: '8px',
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              {TICKERS.map(t => <option key={t} value={t} style={{ background: '#111' }}>{t}</option>)}
            </select>
            {TFS.map((t, i) => {
              const active = tf === t;
              return (
                <button
                  key={t}
                  onClick={() => setTf(t)}
                  style={{
                    fontFamily: T.sans,
                    fontSize: '11px',
                    letterSpacing: '1px',
                    textTransform: 'uppercase',
                    color: active ? 'rgba(255,255,255,0.88)' : T.textMuted,
                    background: active ? 'rgba(255,255,255,0.06)' : 'transparent',
                    border: 'none',
                    borderRight: `0.5px solid ${T.border}`,
                    borderLeft: i === 0 ? `0.5px solid ${T.border}` : 'none',
                    padding: '3px 10px',
                    cursor: 'pointer',
                    fontWeight: active ? 500 : 400,
                  }}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ padding: '0' }}>
          {chartLoading ? (
            <div style={{ padding: '24px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px,1fr))', borderBottom: `0.5px solid ${T.border}` }}>
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} style={{ padding: '14px 24px', borderRight: i < 3 ? `0.5px solid ${T.border}` : 'none' }}>
                    <SkeletonBlock width="46%" height={10} style={{ marginBottom: '10px' }} />
                    <SkeletonBlock width="58%" height={22} />
                  </div>
                ))}
              </div>
              <div style={{ padding: '32px 8px 24px' }}>
                <SkeletonBlock width="100%" height={420} />
              </div>
            </div>
          ) : chart?.ohlcv?.length > 0 ? (
            <PriceChart chart={chart} ticker={ticker} tf={tf} />
          ) : (
            <div style={{ padding: '40px 24px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>No chart data available</span>
            </div>
          )}
        </div>
      </div>

    </main>
  );
}
