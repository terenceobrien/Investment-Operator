'use client';

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { SkeletonMetricGrid, SkeletonRows, SkeletonText } from '@/components/Skeleton';
import { T, sx, formatAccountingPct, formatCurrency, formatRelativeAge, freshnessColor } from '@/lib/tokens';

export default function DailyBrief() {
  const { data: macro, isLoading: macroLoading } = useSWR('/api/brief/macro', fetcher, { refreshInterval: 900000 });
  const { data: moves, isLoading: movesLoading } = useSWR('/api/brief/moves', fetcher, { refreshInterval: 300000 });
  const { data: summary, isLoading: summaryLoading } = useSWR('/api/brief/summary', fetcher, { refreshInterval: 86400000 });
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);

  const today = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    if (macro || moves || summary) setUpdatedAt(Date.now());
  }, [macro, moves, summary]);

  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>Macro Brief</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <span style={sx.sectionMeta}>{today}</span>
              <span style={{ ...sx.sectionMeta, color: freshnessColor(updatedAt) }}>{formatRelativeAge(updatedAt)}</span>
            </div>
          </div>
        </section>

        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>What matters today</span>
            {summary?.fallback ? <span style={{ ...sx.sectionMeta, color: T.wa }}>Heuristic — LLM unavailable</span> : null}
          </div>
          <div style={sx.panelBody}>
            {summaryLoading ? (
              <SkeletonText lines={4} widths={['96%', '92%', '90%', '74%']} lineHeight={12} />
            ) : summary?.summary ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                {summary.summary
                  .split('\n')
                  .filter((line: string) => line.trim())
                  .map((line: string, i: number) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        gap: '12px',
                        padding: '12px 0',
                        borderBottom: `0.5px solid ${T.borderSub}`,
                      }}
                    >
                      <div
                        style={{
                          width: '3px',
                          height: '3px',
                          borderRadius: '50%',
                          background: T.textMuted,
                          marginTop: '7px',
                          flexShrink: 0,
                        }}
                      />
                      <p
                        style={{
                          fontFamily: T.sans,
                          fontSize: '14.5px',
                          color: 'rgba(255,255,255,0.72)',
                          lineHeight: 1.6,
                          margin: 0,
                        }}
                      >
                        {line.trim()}
                      </p>
                    </div>
                  ))}
              </div>
            ) : (
              <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>Summary unavailable.</span>
            )}
          </div>
        </section>

        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>Macro regime</span>
            <span style={sx.sectionMeta}>Growth · Inflation · Liquidity</span>
          </div>
          {macroLoading ? (
            <div style={sx.panelBody}>
              <SkeletonMetricGrid columns={3} items={3} />
            </div>
          ) : (
            <div style={{ ...sx.panelBody, paddingTop: '0' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))', gap: '12px' }}>
                {macro && Object.entries(macro).map(([key, signal]: [string, any]) => {
                  const trend = signal.trend ?? '';
                  const isDown = trend === 'DOWN';
                  const isUp = trend === 'UP';
                  const badgeColor = isUp ? T.up : isDown ? T.dn : T.wa;
                  const valColor = isUp ? T.up : isDown ? T.dn : T.wa;
                  return (
                    <div key={key} style={sx.subPanel}>
                      <div style={{ padding: '16px 18px' }}>
                        <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '8px' }}>
                          {key}
                        </div>
                        <span
                          style={{
                            display: 'inline-block',
                            fontFamily: T.sans,
                            fontSize: '10.5px',
                            letterSpacing: '1px',
                            textTransform: 'uppercase',
                            padding: '2px 7px',
                            marginBottom: '10px',
                            fontWeight: 500,
                            color: badgeColor,
                            background: `${badgeColor}10`,
                            border: `0.5px solid ${badgeColor}40`,
                          }}
                        >
                          {trend || '—'}
                        </span>
                        <div style={{ fontFamily: T.mono, fontSize: '22px', fontWeight: 300, letterSpacing: '-0.5px', color: valColor, marginBottom: '6px' }}>
                          {signal.latest !== undefined ? `${signal.latest >= 0 ? '+' : ''}${signal.latest.toFixed(2)}σ` : '—'}
                        </div>
                        <div style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color: T.textMuted, letterSpacing: '0.3px' }}>
                          MoM {signal.mom !== undefined ? (signal.mom >= 0 ? '+' : '') + signal.mom.toFixed(2) : '—'}
                          {' · '}
                          YoY {signal.yoy !== undefined ? (signal.yoy >= 0 ? '+' : '') + signal.yoy.toFixed(2) : '—'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        <section style={sx.panel}>
          <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
            <span style={sx.sectionLabel}>Market moves</span>
            <span style={sx.sectionMeta}>Ticker · Last · 1D chg</span>
          </div>
          {movesLoading ? (
            <div style={sx.panelBody}>
              <SkeletonRows rows={7} columns={3} />
            </div>
          ) : (
            <div style={{ ...sx.panelBody, paddingTop: '0' }}>
              <div style={sx.subPanel}>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr 1fr',
                    padding: '10px 18px',
                    borderBottom: `0.5px solid ${T.borderSub}`,
                    background: 'rgba(255,255,255,0.012)',
                  }}
                >
                  {['Ticker', 'Last', '1D Change'].map((h, i) => (
                    <span
                      key={h}
                      style={{
                        fontFamily: T.sans,
                        fontSize: '11px',
                        letterSpacing: '1px',
                        textTransform: 'uppercase',
                        color: T.textMuted,
                        textAlign: i > 0 ? 'right' : 'left',
                      }}
                    >
                      {h}
                    </span>
                  ))}
                </div>
                {moves && moves.map((row: any) => {
                  const isPos = row.chg_pct_1d >= 0;
                  const c = isPos ? T.up : T.dn;
                  return (
                    <div
                      key={row.ticker}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr 1fr',
                        padding: '10px 18px',
                        borderBottom: `0.5px solid ${T.borderSub}`,
                        alignItems: 'center',
                      }}
                    >
                      <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 400, color: 'rgba(255,255,255,0.82)', letterSpacing: '0.3px' }}>
                        {row.ticker}
                      </span>
                      <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.textMuted, textAlign: 'right' }}>
                        {formatCurrency(row.last)}
                      </span>
                      <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: c, textAlign: 'right' }}>
                        {row.chg_pct_1d === undefined || row.chg_pct_1d === null ? '—' : formatAccountingPct(row.chg_pct_1d)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
