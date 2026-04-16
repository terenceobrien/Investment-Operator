'use client';

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { SkeletonMetricGrid, SkeletonRows, SkeletonText } from '@/components/Skeleton';
import { T, sx, pct, formatCurrency, formatRelativeAge, freshnessColor } from '@/lib/tokens';

export default function DailyBrief() {
  const { data: macro,   isLoading: macroLoading }   = useSWR('/api/brief/macro',   fetcher, { refreshInterval: 900000 });
  const { data: moves,   isLoading: movesLoading }   = useSWR('/api/brief/moves',   fetcher, { refreshInterval: 300000 });
  const { data: summary, isLoading: summaryLoading } = useSWR('/api/brief/summary', fetcher, { refreshInterval: 86400000 });
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);

  const today = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    if (macro || moves || summary) {
      setUpdatedAt(Date.now());
    }
  }, [macro, moves, summary]);

  return (
    <main style={sx.main}>

      {/* ── Section header ───────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Macro Brief</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span style={sx.sectionMeta}>{today}</span>
            <span style={{ ...sx.sectionMeta, color: freshnessColor(updatedAt) }}>{formatRelativeAge(updatedAt)}</span>
          </div>
        </div>
      </div>

      {/* ── What matters today ───────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>What matters today</span>
          {summary?.fallback && (
            <span style={{ ...sx.sectionMeta, color: T.wa }}>Heuristic — LLM unavailable</span>
          )}
        </div>
        <div style={{ padding: '20px 24px' }}>
          {summaryLoading ? (
            <SkeletonText
              lines={4}
              widths={['96%', '92%', '90%', '74%']}
              lineHeight={12}
            />
          ) : summary?.summary ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
              {summary.summary
                .split('\n')
                .filter((line: string) => line.trim())
                .map((line: string, i: number) => (
                  <div key={i} style={{
                    display: 'flex',
                    gap: '12px',
                    padding: '10px 0',
                    borderBottom: `0.5px solid ${T.borderSub}`,
                  }}>
                    <div style={{
                      width: '3px',
                      height: '3px',
                      borderRadius: '50%',
                      background: T.textMuted,
                      marginTop: '7px',
                      flexShrink: 0,
                    }} />
                    <p style={{
                      fontFamily: T.sans,
                      fontSize: '14.5px',
                      color: 'rgba(255,255,255,0.72)',
                      lineHeight: 1.6,
                      margin: 0,
                    }}>
                      {line.trim()}
                    </p>
                  </div>
                ))}
            </div>
          ) : (
            <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>Summary unavailable.</span>
          )}
        </div>
      </div>

      {/* ── Macro regime ─────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Macro regime</span>
          <span style={sx.sectionMeta}>Growth · Inflation · Liquidity</span>
        </div>
        {macroLoading ? (
          <SkeletonMetricGrid columns={3} items={3} />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))' }}>
            {macro && Object.entries(macro).map(([key, signal]: [string, any], i: number) => {
              const trend  = signal.trend ?? '';
              const isDown = trend === 'DOWN';
              const isUp   = trend === 'UP';
              const badgeColor = isUp ? T.up : isDown ? T.dn : T.wa;
              const valColor   = isUp ? T.up : isDown ? T.dn : T.wa;
              return (
                <div key={key} style={{
                  padding: '14px 24px',
                  borderRight: i < Object.keys(macro).length - 1 ? `0.5px solid ${T.border}` : 'none',
                }}>
                  <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '6px' }}>
                    {key}
                  </div>
                  <span style={{
                    display: 'inline-block',
                    fontFamily: T.sans,
                    fontSize: '10.5px',
                    letterSpacing: '1px',
                    textTransform: 'uppercase',
                    padding: '2px 7px',
                    marginBottom: '8px',
                    fontWeight: 500,
                    color: badgeColor,
                    background: `${badgeColor}10`,
                    border: `0.5px solid ${badgeColor}40`,
                  }}>
                    {trend || '—'}
                  </span>
                  <div style={{ fontFamily: T.mono, fontSize: '22px', fontWeight: 300, letterSpacing: '-0.5px', color: valColor, marginBottom: '5px' }}>
                    {signal.latest !== undefined
                      ? `${signal.latest >= 0 ? '+' : ''}${signal.latest.toFixed(2)}σ`
                      : '—'}
                  </div>
                  <div style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color: T.textMuted, letterSpacing: '0.3px' }}>
                    MoM {signal.mom !== undefined ? (signal.mom >= 0 ? '+' : '') + signal.mom.toFixed(2) : '—'}
                    {' · '}
                    YoY {signal.yoy !== undefined ? (signal.yoy >= 0 ? '+' : '') + signal.yoy.toFixed(2) : '—'}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Market moves ─────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
          <span style={sx.sectionLabel}>Market moves</span>
          <span style={sx.sectionMeta}>Ticker · Last · 1D chg</span>
        </div>
        {movesLoading ? (
          <SkeletonRows rows={7} columns={3} />
        ) : (
          <div>
            {/* Column headers */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              padding: '6px 24px',
              borderBottom: `0.5px solid ${T.borderSub}`,
            }}>
              {['Ticker', 'Last', '1D Change'].map((h, i) => (
                <span key={h} style={{
                  fontFamily: T.sans,
                  fontSize: '11px',
                  letterSpacing: '1px',
                  textTransform: 'uppercase',
                  color: T.textMuted,
                  textAlign: i > 0 ? 'right' : 'left',
                }}>{h}</span>
              ))}
            </div>
            {moves && moves.map((row: any) => {
              const isPos = row.chg_pct_1d >= 0;
              const c     = isPos ? T.up : T.dn;
              return (
                <div key={row.ticker} style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr 1fr',
                  padding: '8px 24px',
                  borderBottom: `0.5px solid ${T.borderSub}`,
                  alignItems: 'center',
                }}>
                  <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 400, color: 'rgba(255,255,255,0.82)', letterSpacing: '0.3px' }}>
                    {row.ticker}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.textMuted, textAlign: 'right' }}>
                    {formatCurrency(row.last)}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: c, textAlign: 'right' }}>
                    {row.chg_pct_1d === undefined || row.chg_pct_1d === null ? '—' : pct(row.chg_pct_1d)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

    </main>
  );
}
