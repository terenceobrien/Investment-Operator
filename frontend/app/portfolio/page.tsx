'use client';

import { useState, useRef } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

export default function PortfolioPage() {
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const analyze = async (file: File) => {
    setLoading(true);
    setError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch(`${API_URL}/api/portfolio/analyze`, {
        method: 'POST',
        body: form,
      });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      const data = await res.json();
      setResult(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) analyze(file);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) analyze(file);
  };

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff', background: '#0a0a0a', minHeight: '100vh' }}>

      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.25rem' }}>Portfolio Snapshot</h1>
      <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '2rem' }}>
        Upload a CSV with columns: ticker, weight, theme
      </p>

      {/* Upload zone */}
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        style={{
          border: `2px dashed ${dragOver ? '#fff' : '#333'}`,
          borderRadius: '12px',
          padding: '3rem',
          textAlign: 'center',
          cursor: 'pointer',
          marginBottom: '2rem',
          transition: 'border-color 0.15s',
          background: dragOver ? '#111' : 'transparent',
        }}
      >
        <p style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem', color: dragOver ? '#fff' : '#9ca3af' }}>
          {loading ? 'Analyzing...' : 'Drop your CSV here or click to upload'}
        </p>
        <p style={{ fontSize: '0.8125rem', color: '#4b5563', margin: 0 }}>
          CSV format: ticker, weight, theme
        </p>
        <input ref={fileRef} type="file" accept=".csv" onChange={onFile} style={{ display: 'none' }} />
      </div>

      {error && (
        <div style={{ background: '#1c0a0a', border: '1px solid #7f1d1d', borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '1.5rem' }}>
          <p style={{ color: '#f87171', margin: 0, fontSize: '0.875rem' }}>{error}</p>
        </div>
      )}

      {result && (
        <>
          {/* Summary metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.75rem', marginBottom: '2rem' }}>
            {[
              { label: 'Positions', value: result.summary.n_positions },
              { label: 'Cash', value: `${(result.summary.cash_weight * 100).toFixed(1)}%` },
              { label: 'Top 1', value: `${(result.summary.top1_invested * 100).toFixed(1)}%` },
              { label: 'Top 3', value: `${(result.summary.top3_invested * 100).toFixed(1)}%` },
              { label: 'Top 5', value: `${(result.summary.top5_invested * 100).toFixed(1)}%` },
            ].map(({ label, value }) => (
              <div key={label} style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '0.875rem 1rem' }}>
                <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 0.25rem' }}>{label}</p>
                <p style={{ fontSize: '1.25rem', fontWeight: 600, margin: 0 }}>{value}</p>
              </div>
            ))}
          </div>

          {/* Flags */}
          {result.flags?.length > 0 && (
            <section style={{ marginBottom: '2rem' }}>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.75rem' }}>Flags</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {result.flags.map((flag: string, i: number) => (
                  <div key={i} style={{ background: '#1c1200', border: '1px solid #854d0e', borderRadius: '8px', padding: '0.75rem 1rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                    <span style={{ color: '#fbbf24', fontSize: '0.875rem', flexShrink: 0 }}>⚠</span>
                    <p style={{ margin: 0, fontSize: '0.875rem', color: '#fde68a', lineHeight: 1.5 }}>{flag}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Top positions */}
          <section style={{ marginBottom: '2rem' }}>
            <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.75rem' }}>Top positions</h2>
            <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #222' }}>
                    <th style={{ padding: '0.75rem 1rem', textAlign: 'left', color: '#6b7280', fontWeight: 500 }}>Ticker</th>
                    <th style={{ padding: '0.75rem 1rem', textAlign: 'left', color: '#6b7280', fontWeight: 500 }}>Theme</th>
                    <th style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#6b7280', fontWeight: 500 }}>Weight</th>
                    <th style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#6b7280', fontWeight: 500 }}>Share of invested</th>
                  </tr>
                </thead>
                <tbody>
                  {result.top_positions.map((pos: any, i: number) => (
                    <tr key={pos.ticker} style={{ borderTop: i === 0 ? 'none' : '1px solid #1a1a1a' }}>
                      <td style={{ padding: '0.75rem 1rem', fontWeight: 500 }}>{pos.ticker}</td>
                      <td style={{ padding: '0.75rem 1rem', color: '#9ca3af' }}>{pos.theme || '—'}</td>
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>{(pos.weight * 100).toFixed(1)}%</td>
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#9ca3af' }}>{(pos.w_norm * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Theme exposure */}
          <section style={{ marginBottom: '2rem' }}>
            <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.75rem' }}>Theme exposure</h2>
            <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem 1.25rem' }}>
              {result.theme_exposure.map((t: any, i: number) => (
                <div key={t.theme} style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '0.5rem 0', borderTop: i === 0 ? 'none' : '1px solid #1a1a1a' }}>
                  <span style={{ fontSize: '0.875rem', color: '#d1d5db', width: '160px', flexShrink: 0 }}>{t.theme}</span>
                  <div style={{ flex: 1, height: '6px', background: '#222', borderRadius: '3px' }}>
                    <div style={{ width: `${t.weight * 100}%`, height: '6px', background: '#60a5fa', borderRadius: '3px' }} />
                  </div>
                  <span style={{ fontSize: '0.875rem', fontWeight: 500, width: '48px', textAlign: 'right' }}>
                    {(t.weight * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Upload another */}
          <button
            onClick={() => { setResult(null); setError(null); }}
            style={{ background: 'transparent', border: '1px solid #333', borderRadius: '8px', padding: '0.5rem 1rem', color: '#9ca3af', fontSize: '0.875rem', cursor: 'pointer' }}
          >
            Upload another portfolio
          </button>
        </>
      )}

    </main>
  );
}