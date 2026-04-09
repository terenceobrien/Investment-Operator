'use client';

import useSWR from 'swr';
import { fetcher } from '../../lib/api';

export default function DailyBrief() {
  const { data: macro, isLoading: macroLoading } = useSWR('/api/brief/macro', fetcher, { refreshInterval: 900000 });
  const { data: moves, isLoading: movesLoading } = useSWR('/api/brief/moves', fetcher, { refreshInterval: 300000 });
  const { data: summary, isLoading: summaryLoading } = useSWR('/api/brief/summary', fetcher, { refreshInterval: 86400000 });

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff', background: '#0a0a0a', minHeight: '100vh' }}>

      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.25rem' }}>Daily Brief</h1>
      <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '2rem' }}>
        {new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
      </p>

      {/* LLM Summary */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>What matters today</h2>
        <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1.25rem' }}>
          {summaryLoading ? (
            <p style={{ color: '#6b7280', margin: 0 }}>Generating summary...</p>
          ) : summary?.summary ? (
            <div style={{ lineHeight: 1.7, fontSize: '0.9375rem' }}>
                {summary.summary.split('\n').filter((line: string) => line.trim()).map((line: string, i: number) => (
                    <p key={i} style={{ margin: '0 0 0.5rem' }}>{line.trim()}</p>
            ))}
            </div>
          ) : (
            <p style={{ color: '#6b7280', margin: 0 }}>Summary unavailable.</p>
          )}
          {summary?.fallback && (
            <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0.75rem 0 0' }}>Heuristic summary — LLM unavailable</p>
          )}
        </div>
      </section>

      {/* Macro regime */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Macro regime</h2>
        {macroLoading ? (
          <p style={{ color: '#6b7280' }}>Loading macro data...</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
            {macro && Object.entries(macro).map(([key, signal]: [string, any]) => {
              const trendColor = signal.trend === 'UP' ? '#4ade80' : signal.trend === 'DOWN' ? '#f87171' : '#facc15';
              return (
                <div key={key} style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <p style={{ fontSize: '0.875rem', fontWeight: 600, margin: 0 }}>{key}</p>
                    <span style={{
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      padding: '2px 8px',
                      borderRadius: '999px',
                      background: `${trendColor}22`,
                      color: trendColor,
                    }}>
                      {signal.trend}
                    </span>
                  </div>
                  <p style={{ fontSize: '1.5rem', fontWeight: 600, margin: '0 0 0.25rem' }}>
                    {signal.latest?.toFixed(2)}σ
                  </p>
                  <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.75rem' }}>{signal.name}</p>
                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <div>
                      <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 2px' }}>MoM</p>
                      <p style={{ fontSize: '0.8125rem', fontWeight: 500, margin: 0, color: signal.mom >= 0 ? '#4ade80' : '#f87171' }}>
                        {signal.mom >= 0 ? '+' : ''}{signal.mom?.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 2px' }}>YoY</p>
                      <p style={{ fontSize: '0.8125rem', fontWeight: 500, margin: 0, color: signal.yoy >= 0 ? '#4ade80' : '#f87171' }}>
                        {signal.yoy >= 0 ? '+' : ''}{signal.yoy?.toFixed(2)}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Market moves */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Market moves</h2>
        {movesLoading ? (
          <p style={{ color: '#6b7280' }}>Loading market data...</p>
        ) : (
          <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #222' }}>
                  <th style={{ padding: '0.75rem 1rem', textAlign: 'left', color: '#6b7280', fontWeight: 500 }}>Ticker</th>
                  <th style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#6b7280', fontWeight: 500 }}>Last</th>
                  <th style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#6b7280', fontWeight: 500 }}>1D Change</th>
                </tr>
              </thead>
              <tbody>
                {moves && moves.map((row: any, i: number) => {
                  const isPos = row.chg_pct_1d >= 0;
                  return (
                    <tr key={row.ticker} style={{ borderTop: i === 0 ? 'none' : '1px solid #1a1a1a' }}>
                      <td style={{ padding: '0.75rem 1rem', fontWeight: 500 }}>{row.ticker}</td>
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#9ca3af' }}>
                        {row.last?.toFixed(2)}
                      </td>
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: isPos ? '#4ade80' : '#f87171', fontWeight: 500 }}>
                        {isPos ? '+' : ''}{row.chg_pct_1d?.toFixed(2)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

    </main>
  );
}