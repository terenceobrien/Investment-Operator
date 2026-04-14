'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { T, sx, pct } from '@/lib/tokens';

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
      }}>
        {HORIZONS.map((h, i) => {
          const active = horizon === h;
          return (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              style={{
                fontFamily: T.sans,
                fontSize: '10px',
                letterSpacing: '1px',
                textTransform: 'uppercase',
                color: active ? 'rgba(255,255,255,0.8)' : T.textMuted,
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
          <div style={{ padding: '20px 24px' }}>
            <span style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted }}>Loading...</span>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, minmax(0,1fr))' }}>
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
                  <span style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '0.5px', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>
                    {item.name || item.ticker}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: text, letterSpacing: '-0.3px' }}>
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
          <div style={{ padding: '20px 24px' }}>
            <span style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted }}>Loading...</span>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0,1fr))' }}>
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
                  <span style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '0.5px', color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>
                    {item.name || item.ticker}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: text, letterSpacing: '-0.3px' }}>
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '0' }}>
            <select
              value={ticker}
              onChange={e => setTicker(e.target.value)}
              style={{
                fontFamily: T.mono,
                fontSize: '10px',
                letterSpacing: '0.5px',
                color: 'rgba(255,255,255,0.6)',
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
                    fontSize: '9px',
                    letterSpacing: '1px',
                    textTransform: 'uppercase',
                    color: active ? 'rgba(255,255,255,0.8)' : T.textMuted,
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
            <div style={{ padding: '40px 24px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted }}>Loading chart...</span>
            </div>
          ) : chart?.ohlcv?.length > 0 ? (() => {
            const closes  = chart.ohlcv.map((d: any) => d.Close);
            const first   = closes[0];
            const last    = closes[closes.length - 1];
            const change  = last - first;
            const chgPct  = (change / first) * 100;
            const isPos   = change >= 0;
            const lineCol = isPos ? T.up : T.dn;
            const min     = Math.min(...closes);
            const max     = Math.max(...closes);
            const range   = max - min || 1;
            const W = 1000, H = 160;
            const points  = closes.map((c: number, i: number) => {
              const x = (i / (closes.length - 1)) * W;
              const y = H - ((c - min) / range) * H * 0.85 - H * 0.075;
              return `${x},${y}`;
            }).join(' ');

            return (
              <div>
                {/* Chart stats row */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, minmax(0,1fr))',
                  borderBottom: `0.5px solid ${T.border}`,
                }}>
                  {[
                    { label: `${ticker} last`, val: `$${last?.toFixed(2)}`, color: T.text },
                    { label: `Change (${tf})`,  val: pct(chgPct),           color: isPos ? T.up : T.dn },
                    { label: 'High',            val: `$${Math.max(...closes).toFixed(2)}`, color: T.text },
                    { label: 'Low',             val: `$${Math.min(...closes).toFixed(2)}`, color: T.text },
                  ].map(({ label, val, color }, i) => (
                    <div key={label} style={{
                      padding: '12px 24px',
                      borderRight: i < 3 ? `0.5px solid ${T.border}` : 'none',
                    }}>
                      <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                        {label}
                      </div>
                      <div style={{ fontFamily: T.mono, fontSize: '18px', fontWeight: 300, letterSpacing: '-0.5px', color }}>
                        {val}
                      </div>
                    </div>
                  ))}
                </div>

                {/* SVG chart */}
                <div style={{ padding: '24px 24px 20px' }}>
                  <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '180px', display: 'block' }}>
                    <polyline
                      points={points}
                      fill="none"
                      stroke={lineCol}
                      strokeWidth="1"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
              </div>
            );
          })() : (
            <div style={{ padding: '40px 24px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted }}>No chart data available</span>
            </div>
          )}
        </div>
      </div>

    </main>
  );
}