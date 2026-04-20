'use client';

import { MouseEvent, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { SkeletonBlock } from '@/components/Skeleton';
import { T, sx, pct, formatCurrency, formatNumber } from '@/lib/tokens';

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

function formatCompactVolume(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${formatNumber(value / 1_000_000_000, 2)}B`;
  if (abs >= 1_000_000) return `${formatNumber(value / 1_000_000, 2)}M`;
  if (abs >= 1_000) return `${formatNumber(value / 1_000, 1)}K`;
  return formatNumber(value, 0);
}

function PriceChart({ chart, ticker, tf }: { chart: any; ticker: string; tf: string }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  type ChartPoint = {
    idx: number;
    rawTime: string | number;
    timestamp: Date;
    open: number;
    high: number;
    low: number;
    price: number;
    volume: number;
  };

  const chartData: ChartPoint[] = useMemo(() => chart.ohlcv.map((d: any, idx: number) => {
    const rawTime = getTimestamp(d);
    return {
      idx,
      rawTime,
      timestamp: new Date(rawTime),
      open: Number(d.Open),
      high: Number(d.High),
      low: Number(d.Low),
      price: Number(d.Close),
      volume: Number(d.Volume ?? 0),
    };
  }), [chart.ohlcv]);

  const opens = chartData.map((d) => d.open);
  const highs = chartData.map((d) => d.high);
  const lows = chartData.map((d) => d.low);
  const closes = chartData.map((d) => d.price);
  const volumes = chartData.map((d) => d.volume);
  const first = closes[0];
  const last = closes[closes.length - 1];
  const change = last - first;
  const chgPct = (change / first) * 100;
  const isPos = change >= 0;
  const lineCol = isPos ? T.up : T.dn;
  const priceMin = Math.min(...lows);
  const priceMax = Math.max(...highs);
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

  const xForIndex = (idx: number) => padLeft + (idx / Math.max(chartData.length - 1, 1)) * plotWidth;
  const yForPrice = (price: number) => padTop + ((domainMax - price) / (domainMax - domainMin || 1)) * plotHeight;

  const points = chartData.map((point, idx) => {
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

  const rangeValue = priceMax - priceMin;
  const rangePct = priceMin > 0 ? (rangeValue / priceMin) * 100 : null;
  const totalVolume = volumes.reduce((sum: number, value: number) => sum + value, 0);
  const distanceFromHigh = priceMax > 0 ? ((last / priceMax) - 1) * 100 : null;
  const distanceFromLow = priceMin > 0 ? ((last / priceMin) - 1) * 100 : null;

  const stats = [
    { label: `${ticker} last`, value: formatCurrency(last), color: T.text },
    { label: 'Abs change', value: formatCurrency(change), color: isPos ? T.up : T.dn },
    { label: `Return (${tf})`, value: pct(chgPct), color: isPos ? T.up : T.dn },
    { label: 'Open', value: formatCurrency(opens[0]), color: T.text },
    { label: 'High', value: formatCurrency(priceMax), color: T.text },
    { label: 'Low', value: formatCurrency(priceMin), color: T.text },
    { label: 'Range', value: formatCurrency(rangeValue), color: T.text, sub: rangePct != null ? pct(rangePct) : undefined },
    { label: 'Volume', value: formatCompactVolume(totalVolume), color: T.text },
    { label: 'Off high', value: distanceFromHigh != null ? pct(distanceFromHigh) : '—', color: (distanceFromHigh ?? 0) >= 0 ? T.up : T.dn },
    { label: 'Off low', value: distanceFromLow != null ? pct(distanceFromLow) : '—', color: (distanceFromLow ?? 0) >= 0 ? T.up : T.dn },
  ];

  const onMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    const svgRect = svgRef.current?.getBoundingClientRect();
    if (!svgRect) return;

    const plotLeft = svgRect.left + (padLeft / svgWidth) * svgRect.width;
    const plotRight = svgRect.left + ((svgWidth - padRight) / svgWidth) * svgRect.width;
    const plotPixelWidth = Math.max(plotRight - plotLeft, 1);
    const clampedX = Math.min(plotRight, Math.max(plotLeft, event.clientX));
    const ratio = (clampedX - plotLeft) / plotPixelWidth;
    const idx = Math.round(ratio * Math.max(chartData.length - 1, 1));
    setHoveredIndex(Math.max(0, Math.min(chartData.length - 1, idx)));
  };

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'stretch',
        borderBottom: `0.5px solid ${T.border}`,
      }}
    >
      <div
        style={{
          flex: '1 1 720px',
          minWidth: 0,
          borderRight: `0.5px solid ${T.border}`,
        }}
      >
        <div style={{ padding: '28px 12px 24px 8px' }}>
          <div style={{ position: 'relative', overflow: 'visible' }}>
            <svg
              ref={svgRef}
              key={`${ticker}-${tf}`}
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              width="100%"
              height="360"
              role="img"
              aria-label={`${ticker} price chart`}
              style={{ overflow: 'visible', display: 'block' }}
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

            <div
              onMouseMove={onMouseMove}
              onMouseLeave={() => setHoveredIndex(null)}
              style={{
                position: 'absolute',
                inset: 0,
                cursor: 'crosshair',
              }}
            />

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

      <div
        style={{
          flex: '0 1 320px',
          width: '320px',
          minWidth: '280px',
          background: 'rgba(255,255,255,0.014)',
        }}
      >
        <div style={{ ...sx.sectionHd, padding: '10px 20px', borderLeft: 'none' }}>
          <span style={sx.sectionLabel}>Price action</span>
          <span style={sx.sectionMeta}>{ticker} · {tf}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))' }}>
          {stats.map((stat, idx) => (
            <div
              key={stat.label}
              style={{
                padding: '14px 20px',
                borderBottom: `0.5px solid ${T.borderSub}`,
                borderRight: idx % 2 === 0 ? `0.5px solid ${T.borderSub}` : 'none',
              }}
            >
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
                {stat.label}
              </div>
              <div style={{ fontFamily: T.mono, fontSize: '18px', fontWeight: 300, letterSpacing: '-0.4px', color: stat.color }}>
                {stat.value}
              </div>
              {stat.sub && (
                <div style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted, marginTop: '4px' }}>
                  {stat.sub}
                </div>
              )}
            </div>
          ))}
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
      <div style={sx.pageShell}>
        <section style={sx.panel}>
          <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
            <span style={sx.sectionLabel}>Market data</span>
            <span style={sx.sectionMeta}>Price action · Sector returns · Charts</span>
          </div>
          <div style={{ ...sx.panelBody, paddingTop: '14px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0',
                overflowX: 'auto',
                scrollbarWidth: 'none',
              }}
            >
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
                      padding: '8px 14px',
                      cursor: 'pointer',
                      fontWeight: active ? 500 : 400,
                    }}
                  >
                    {h}
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>Broad market returns</span>
            <span style={sx.sectionMeta}>{horizon}</span>
          </div>
          {heatmapLoading ? (
            <div style={sx.panelBody}>
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
            <div style={{ ...sx.panelBody, paddingTop: '0' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px,1fr))', gap: '12px' }}>
                {heatmap?.cross?.map((item: any) => {
                  const { bg, text } = heatColor(item.return);
                  return (
                    <div key={item.ticker} style={{ ...sx.subPanel, background: bg }}>
                      <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.5px', color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase' }}>
                          {item.name || item.ticker}
                        </span>
                        <span style={{ fontFamily: T.mono, fontSize: '15px', fontWeight: 300, color: text, letterSpacing: '-0.3px' }}>
                          {item.return !== null ? pct(item.return) : '—'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>Sector returns</span>
            <span style={sx.sectionMeta}>{horizon}</span>
          </div>
          {heatmapLoading ? (
            <div style={sx.panelBody}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(11, minmax(0,1fr))', gap: '1px' }}>
                {Array.from({ length: 11 }).map((_, i) => (
                  <div key={i} style={{ padding: '12px 12px', background: 'rgba(255,255,255,0.02)' }}>
                    <SkeletonBlock width="64%" height={10} style={{ marginBottom: '8px' }} />
                    <SkeletonBlock width="42%" height={15} />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ ...sx.panelBody, paddingTop: '0' }}>
              <div style={sx.subPanel}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(11, minmax(0,1fr))' }}>
                  {heatmap?.sectors?.map((item: any, i: number) => {
                    const { bg, text } = heatColor(item.return);
                    return (
                      <div
                        key={item.ticker}
                        style={{
                          background: bg,
                          padding: '12px 10px',
                          borderRight: i < heatmap.sectors.length - 1 ? `0.5px solid rgba(255,255,255,0.04)` : 'none',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '4px',
                        }}
                      >
                        <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.4px', color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase' }}>
                          {item.name || item.ticker}
                        </span>
                        <span style={{ fontFamily: T.mono, fontSize: '14px', fontWeight: 300, color: text, letterSpacing: '-0.3px' }}>
                          {item.return !== null ? pct(item.return) : '—'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </section>

        <section style={sx.panel}>
          <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
            <span style={sx.sectionLabel}>Price chart</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <select
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                style={{
                  fontFamily: T.mono,
                  fontSize: '12px',
                  letterSpacing: '0.5px',
                  color: 'rgba(255,255,255,0.75)',
                  background: 'transparent',
                  border: `0.5px solid ${T.border}`,
                  padding: '5px 8px',
                  marginRight: '8px',
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                {TICKERS.map((t) => <option key={t} value={t} style={{ background: '#111' }}>{t}</option>)}
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
                      padding: '5px 10px',
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
          <div>
            {chartLoading ? (
              <div style={sx.panelBody}>
                <div style={{ padding: '16px 8px 8px' }}>
                  <SkeletonBlock width="100%" height={420} />
                </div>
              </div>
            ) : chart?.ohlcv?.length > 0 ? (
              <PriceChart chart={chart} ticker={ticker} tf={tf} />
            ) : (
              <div style={{ ...sx.panelBody, padding: '40px 24px' }}>
                <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>No chart data available</span>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
    </main>
  );
}
