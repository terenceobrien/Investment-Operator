'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { SkeletonBlock } from '@/components/Skeleton';
import { T, sx, pct, formatCurrency } from '@/lib/tokens';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';

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
          ) : chart?.ohlcv?.length > 0 ? (() => {
            const closes   = chart.ohlcv.map((d: any) => d.Close);
            const first    = closes[0];
            const last     = closes[closes.length - 1];
            const change   = last - first;
            const chgPct   = (change / first) * 100;
            const isPos    = change >= 0;
            const lineCol  = isPos ? T.up : T.dn;
            const priceMin = Math.min(...closes);
            const priceMax = Math.max(...closes);
            const padding  = (priceMax - priceMin) * 0.08 || 1;

            const chartData = chart.ohlcv.map((d: any) => ({
              date:  (d.Date || d.Datetime || '').toString().slice(0, 10),
              price: d.Close,
            }));

            return (
              <div>
                {/* Chart stats row */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(160px,1fr))',
                  borderBottom: `0.5px solid ${T.border}`,
                }}>
                  {[
                    { label: `${ticker} last`, val: formatCurrency(last), color: T.text },
                    { label: `Change (${tf})`,  val: pct(chgPct),           color: isPos ? T.up : T.dn },
                    { label: 'High',            val: formatCurrency(priceMax), color: T.text },
                    { label: 'Low',             val: formatCurrency(priceMin), color: T.text },
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

                {/* Recharts line chart */}
                <div style={{ padding: '32px 8px 24px' }}>
                  <ResponsiveContainer width="100%" height={420}>
                    <LineChart data={chartData} margin={{ top: 8, right: 32, left: 0, bottom: 24 }}>
                      <CartesianGrid
                        stroke="rgba(255,255,255,0.04)"
                        strokeDasharray="0"
                        vertical={false}
                      />
                      <XAxis
                        dataKey="date"
                        tick={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fill: 'rgba(255,255,255,0.35)', fontWeight: 300 }}
                        tickLine={false}
                        axisLine={{ stroke: 'rgba(255,255,255,0.08)' }}
                        interval="preserveStartEnd"
                        tickFormatter={(v: string) => v?.slice(5) ?? ''}
                        dy={8}
                      />
                      <YAxis
                        domain={[priceMin - padding, priceMax + padding]}
                        tick={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fill: 'rgba(255,255,255,0.35)', fontWeight: 300 }}
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(v: number) => formatCurrency(v, 0)}
                        width={58}
                        tickCount={6}
                      />
                      <Tooltip
                        contentStyle={{
                          background: '#0c0c0f',
                          border: '0.5px solid rgba(255,255,255,0.1)',
                          borderRadius: 0,
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: 11,
                          padding: '8px 12px',
                        }}
                        labelStyle={{ color: 'rgba(255,255,255,0.45)', marginBottom: 4, fontSize: 10 }}
                        itemStyle={{ color: lineCol, fontWeight: 300 }}
                        formatter={(value: any) => [formatCurrency(Number(value)), ticker]}
                        cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="price"
                        stroke={lineCol}
                        strokeWidth={1.5}
                        dot={false}
                        activeDot={{ r: 3, fill: lineCol, strokeWidth: 0 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            );
          })() : (
            <div style={{ padding: '40px 24px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>No chart data available</span>
            </div>
          )}
        </div>
      </div>

    </main>
  );
}
