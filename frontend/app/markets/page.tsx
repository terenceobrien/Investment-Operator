'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';

const HORIZONS = ['1D', '1W', '1M', '3M', '6M', '1Y', 'YTD'];

export default function MarketsPage() {
  const [horizon, setHorizon] = useState('1D');
  const [ticker, setTicker] = useState('SPY');
  const [tf, setTf] = useState('1D');

  const { data: heatmap, isLoading: heatmapLoading } = useSWR(
    `/api/prices/heatmap?horizon=${horizon}`,
    fetcher,
    { refreshInterval: 300000 }
  );

  const { data: chart, isLoading: chartLoading } = useSWR(
    `/api/prices/chart?ticker=${ticker}&tf=${tf}`,
    fetcher,
    { refreshInterval: 300000 }
  );

  const getColor = (ret: number | null) => {
    if (ret === null || ret === undefined) return '#1f1f1f';
    if (ret > 1) return '#166534';
    if (ret > 0.3) return '#15803d';
    if (ret > 0) return '#16a34a';
    if (ret > -0.3) return '#dc2626';
    if (ret > -1) return '#b91c1c';
    return '#7f1d1d';
  };

  const getTextColor = (ret: number | null) => {
    if (ret === null || ret === undefined) return '#6b7280';
    return '#fff';
  };

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff', background: '#0a0a0a', minHeight: '100vh' }}>

      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.25rem' }}>Market Data</h1>
      <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '2rem' }}>Price action, sector returns, and charts</p>

      {/* Horizon selector */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '2rem', flexWrap: 'wrap' }}>
        {HORIZONS.map(h => (
          <button
            key={h}
            onClick={() => setHorizon(h)}
            style={{
              padding: '0.375rem 0.875rem',
              borderRadius: '8px',
              border: '1px solid',
              borderColor: horizon === h ? '#fff' : '#333',
              background: horizon === h ? '#fff' : 'transparent',
              color: horizon === h ? '#000' : '#9ca3af',
              fontSize: '0.8125rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            {h}
          </button>
        ))}
      </div>

      {/* Cross asset heatmap */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Broad market returns</h2>
        {heatmapLoading ? (
          <p style={{ color: '#6b7280' }}>Loading...</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: '0.5rem', marginBottom: '2rem' }}>
            {heatmap?.cross?.map((item: any) => (
              <div
                key={item.ticker}
                style={{
                  background: getColor(item.return),
                  borderRadius: '8px',
                  padding: '0.75rem',
                  textAlign: 'center',
                }}
              >
                <p style={{ fontSize: '0.75rem', fontWeight: 600, margin: '0 0 0.25rem', color: getTextColor(item.return) }}>{item.name}</p>
                <p style={{ fontSize: '0.9375rem', fontWeight: 600, margin: 0, color: getTextColor(item.return) }}>
                  {item.return !== null ? `${item.return >= 0 ? '+' : ''}${item.return.toFixed(2)}%` : 'n/a'}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Sector heatmap */}
      <section style={{ marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Sector returns</h2>
        {heatmapLoading ? (
          <p style={{ color: '#6b7280' }}>Loading...</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '0.5rem' }}>
            {heatmap?.sectors?.map((item: any) => (
              <div
                key={item.ticker}
                style={{
                  background: getColor(item.return),
                  borderRadius: '8px',
                  padding: '0.75rem',
                  textAlign: 'center',
                }}
              >
                <p style={{ fontSize: '0.75rem', fontWeight: 600, margin: '0 0 0.25rem', color: getTextColor(item.return) }}>{item.name}</p>
                <p style={{ fontSize: '0.9375rem', fontWeight: 600, margin: 0, color: getTextColor(item.return) }}>
                  {item.return !== null ? `${item.return >= 0 ? '+' : ''}${item.return.toFixed(2)}%` : 'n/a'}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Chart */}
      <section>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Price chart</h2>

        {/* Chart controls */}
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            value={ticker}
            onChange={e => setTicker(e.target.value)}
            style={{
              background: '#111',
              border: '1px solid #333',
              borderRadius: '8px',
              padding: '0.375rem 0.75rem',
              color: '#fff',
              fontSize: '0.875rem',
            }}
          >
            {['SPY', 'QQQ', 'IWM', 'TLT', 'HYG', 'GLD', 'USO', 'BTC-USD'].map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {['1D', '5D', '1M', '3M', 'YTD'].map(t => (
              <button
                key={t}
                onClick={() => setTf(t)}
                style={{
                  padding: '0.375rem 0.75rem',
                  borderRadius: '8px',
                  border: '1px solid',
                  borderColor: tf === t ? '#fff' : '#333',
                  background: tf === t ? '#fff' : 'transparent',
                  color: tf === t ? '#000' : '#9ca3af',
                  fontSize: '0.8125rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Simple line chart using canvas-free approach */}
        <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1.25rem' }}>
          {chartLoading ? (
            <p style={{ color: '#6b7280', margin: 0 }}>Loading chart...</p>
          ) : chart?.ohlcv?.length > 0 ? (
            <div>
              {/* Price summary */}
              <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                {(() => {
                  const first = chart.ohlcv[0]?.Close;
                  const last = chart.ohlcv[chart.ohlcv.length - 1]?.Close;
                  const change = last - first;
                  const changePct = (change / first) * 100;
                  const isPos = change >= 0;
                  return (
                    <>
                      <div>
                        <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>{ticker} last</p>
                        <p style={{ fontSize: '1.5rem', fontWeight: 600, margin: 0 }}>${last?.toFixed(2)}</p>
                      </div>
                      <div>
                        <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Change ({tf})</p>
                        <p style={{ fontSize: '1.5rem', fontWeight: 600, margin: 0, color: isPos ? '#4ade80' : '#f87171' }}>
                          {isPos ? '+' : ''}{changePct.toFixed(2)}%
                        </p>
                      </div>
                      <div>
                        <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>High</p>
                        <p style={{ fontSize: '1.5rem', fontWeight: 600, margin: 0 }}>${Math.max(...chart.ohlcv.map((d: any) => d.High)).toFixed(2)}</p>
                      </div>
                      <div>
                        <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Low</p>
                        <p style={{ fontSize: '1.5rem', fontWeight: 600, margin: 0 }}>${Math.min(...chart.ohlcv.map((d: any) => d.Low)).toFixed(2)}</p>
                      </div>
                    </>
                  );
                })()}
              </div>

              {/* SVG line chart */}
              {(() => {
                const closes = chart.ohlcv.map((d: any) => d.Close);
                const min = Math.min(...closes);
                const max = Math.max(...closes);
                const range = max - min || 1;
                const w = 800;
                const h = 200;
                const points = closes.map((c: number, i: number) => {
                  const x = (i / (closes.length - 1)) * w;
                  const y = h - ((c - min) / range) * h;
                  return `${x},${y}`;
                }).join(' ');
                const isPos = closes[closes.length - 1] >= closes[0];
                const color = isPos ? '#4ade80' : '#f87171';
                return (
                  <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: '160px' }}>
                    <polyline
                      points={points}
                      fill="none"
                      stroke={color}
                      strokeWidth="1.5"
                    />
                  </svg>
                );
              })()}
            </div>
          ) : (
            <p style={{ color: '#6b7280', margin: 0 }}>No chart data available</p>
          )}
        </div>
      </section>

    </main>
  );
}