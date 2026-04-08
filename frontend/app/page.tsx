'use client';

import useSWR from 'swr';
import { fetcher } from '../lib/api';

export default function Dashboard() {
  const { data, error, isLoading } = useSWR('/api/market/state', fetcher, {
    refreshInterval: 300000,
  });

  if (isLoading) return (
    <div style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff' }}>
      Loading market state...
    </div>
  );

  if (error) return (
    <div style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#f87171' }}>
      Error loading data: {error.message}
    </div>
  );

  const envColor: Record<string, string> = {
    'Risk-On Rotation Day': '#4ade80',
    'Trend Day (Directional)': '#60a5fa',
    'Risk-Off / Headline Risk': '#f87171',
    'Chop / Mean Reversion': '#facc15',
    'Mixed / Neutral': '#a78bfa',
  };

  const color = envColor[data?.environment] || '#a78bfa';

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff', background: '#0a0a0a', minHeight: '100vh' }}>
      
      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.25rem' }}>
        Market State
      </h1>
      <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '2rem' }}>
        {data?.asof_utc?.slice(0, 10)} · {data?.horizon} horizon
      </p>

      {/* Top metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
        
        <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem' }}>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>Sentiment score</p>
          <p style={{ fontSize: '2rem', fontWeight: 600, margin: 0 }}>{data?.score_total?.toFixed(1)}</p>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0.25rem 0 0' }}>out of 100</p>
        </div>

        <div style={{ background: '#111', border: `1px solid ${color}44`, borderRadius: '12px', padding: '1rem' }}>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>Environment</p>
          <p style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color }}>{data?.environment}</p>
        </div>

        <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem' }}>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>Confidence</p>
          <p style={{ fontSize: '2rem', fontWeight: 600, margin: 0 }}>{data?.confidence?.toFixed(0)}</p>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0.25rem 0 0' }}>out of 100</p>
        </div>

        <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem' }}>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>Sectors green</p>
          <p style={{ fontSize: '2rem', fontWeight: 600, margin: 0 }}>{data?.sectors_green}<span style={{ fontSize: '1rem', color: '#6b7280' }}>/11</span></p>
        </div>

        <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem' }}>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>VIX</p>
          <p style={{ fontSize: '2rem', fontWeight: 600, margin: 0 }}>{data?.vix_level?.toFixed(1)}</p>
          <p style={{ fontSize: '0.75rem', color: data?.vix_change_pct_1d > 0 ? '#f87171' : '#4ade80', margin: '0.25rem 0 0' }}>
            {data?.vix_change_pct_1d > 0 ? '+' : ''}{data?.vix_change_pct_1d?.toFixed(2)}% today
          </p>
        </div>

      </div>

      {/* Score components */}
      <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Score components</h2>
      <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem', marginBottom: '2rem' }}>
        {data?.score_components && Object.entries(data.score_components).map(([key, value]: [string, any]) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '0.5rem 0', borderTop: '1px solid #1f1f1f' }}>
            <span style={{ fontSize: '0.875rem', color: '#9ca3af', width: '160px', flexShrink: 0 }}>
              {key.replace(/_/g, ' ')}
            </span>
            <div style={{ flex: 1, height: '6px', background: '#222', borderRadius: '3px' }}>
              <div style={{ width: `${(value / 10) * 100}%`, height: '6px', background: value >= 6 ? '#4ade80' : value >= 4 ? '#facc15' : '#f87171', borderRadius: '3px' }} />
            </div>
            <span style={{ fontSize: '0.875rem', fontWeight: 500, width: '32px', textAlign: 'right' }}>
              {value?.toFixed(1)}
            </span>
          </div>
        ))}
      </div>

      {/* Leadership */}
      <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Sector leadership</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem', marginBottom: '2rem' }}>
        {data?.leadership_top3?.map(([name, ret]: [string, number], i: number) => (
          <div key={name} style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '0.75rem 1rem' }}>
            <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>#{i + 1}</p>
            <p style={{ fontSize: '0.875rem', fontWeight: 500, margin: '0 0 0.25rem' }}>{name}</p>
            <p style={{ fontSize: '0.875rem', color: ret >= 0 ? '#4ade80' : '#f87171', margin: 0 }}>
              {ret >= 0 ? '+' : ''}{ret?.toFixed(2)}%
            </p>
          </div>
        ))}
      </div>

      {/* SPY tape */}
      <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>SPY tape</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem' }}>
        {[
          { label: 'Last price', value: `$${data?.spy_last_price?.toFixed(2)}` },
          { label: 'VWAP', value: `$${data?.spy_vwap?.toFixed(2)}` },
          { label: 'Above VWAP', value: data?.spy_above_vwap ? 'Yes' : 'No', color: data?.spy_above_vwap ? '#4ade80' : '#f87171' },
          { label: 'Above prev close', value: data?.spy_above_prev_close ? 'Yes' : 'No', color: data?.spy_above_prev_close ? '#4ade80' : '#f87171' },
          { label: 'CLV', value: data?.spy_clv?.toFixed(3) },
          { label: 'Range %', value: `${data?.spy_range_pct?.toFixed(2)}%` },
        ].map(({ label, value, color: c }) => (
          <div key={label} style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '0.75rem 1rem' }}>
            <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>{label}</p>
            <p style={{ fontSize: '1rem', fontWeight: 500, margin: 0, color: c || '#fff' }}>{value}</p>
          </div>
        ))}
      </div>

    </main>
  );
}