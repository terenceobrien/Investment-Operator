'use client';

import { useState, useRef } from 'react';
import { SkeletonBlock } from '@/components/Skeleton';
import { T, sx } from '@/lib/tokens';

export default function PortfolioPage() {
  const [result,   setResult]   = useState<any>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const analyze = async (file: File) => {
    setLoading(true);
    setError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch('/api/portfolio/analyze', { method: 'POST', body: form });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      setResult(await res.json());
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
    <main style={sx.main}>

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
          <span style={sx.sectionLabel}>Portfolio snapshot</span>
          <span style={sx.sectionMeta}>CSV format: ticker, weight, theme</span>
        </div>
      </div>

      {/* ── Upload zone ──────────────────────────────────────────────────── */}
      {!result && (
        <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            style={{
              margin: '32px 24px',
              border: `0.5px dashed ${dragOver ? 'rgba(16,32,51,0.3)' : 'rgba(16,32,51,0.1)'}`,
              padding: '48px 24px',
              textAlign: 'center',
              cursor: loading ? 'default' : 'pointer',
              background: dragOver ? 'rgba(16,32,51,0.02)' : 'transparent',
              transition: 'border-color 0.12s, background 0.12s',
            }}
          >
            <div style={{
              fontFamily: T.sans,
              fontSize: '13px',
              fontWeight: 300,
              letterSpacing: '0.5px',
              color: dragOver ? 'rgba(16,32,51,0.75)' : T.textMuted,
              marginBottom: '6px',
            }}>
              {loading ? 'Preparing snapshot' : 'Drop CSV here or click to upload'}
            </div>
            <div style={{ fontFamily: T.sans, fontSize: '12px', color: 'rgba(16,32,51,0.35)', letterSpacing: '0.3px' }}>
              ticker · weight · theme
            </div>
            {loading && (
              <div style={{ marginTop: '18px', display: 'flex', flexDirection: 'column', gap: '10px', alignItems: 'center' }}>
                <SkeletonBlock width="58%" height={12} />
                <SkeletonBlock width="72%" height={12} />
              </div>
            )}
            <input ref={fileRef} type="file" accept=".csv" onChange={onFile} style={{ display: 'none' }} />
          </div>

          {error && (
            <div style={{ margin: '0 24px 24px', padding: '10px 14px', border: `0.5px solid ${T.dn}40`, background: `${T.dn}08` }}>
              <span style={{ fontFamily: T.sans, fontSize: '12px', fontWeight: 300, color: T.dn }}>{error}</span>
            </div>
          )}
        </div>
      )}

      {/* ── Results ──────────────────────────────────────────────────────── */}
      {result && (
        <>
          {/* Summary metrics */}
          <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
            <div style={sx.sectionHd}>
              <span style={sx.sectionLabel}>Summary</span>
              <button
                onClick={() => { setResult(null); setError(null); }}
                style={{
                  fontFamily: T.sans,
                  fontSize: '11px',
                  letterSpacing: '1px',
                  textTransform: 'uppercase',
                  color: T.textMuted,
                  background: 'transparent',
                  border: `0.5px solid ${T.border}`,
                  padding: '3px 10px',
                  cursor: 'pointer',
                }}
              >
                Upload new
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
              {[
                { label: 'Positions',      value: result.summary.n_positions },
                { label: 'Cash weight',    value: `${(result.summary.cash_weight * 100).toFixed(1)}%` },
                { label: 'Top 1 conc.',    value: `${(result.summary.top1_invested * 100).toFixed(1)}%` },
                { label: 'Top 3 conc.',    value: `${(result.summary.top3_invested * 100).toFixed(1)}%` },
                { label: 'Top 5 conc.',    value: `${(result.summary.top5_invested * 100).toFixed(1)}%` },
              ].map(({ label, value }, i) => (
                <div key={label} style={{
                  padding: '14px 24px',
                  borderRight: i < 4 ? `0.5px solid ${T.border}` : 'none',
                }}>
                  <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '8px' }}>
                    {label}
                  </div>
                  <div style={{ fontFamily: T.mono, fontSize: '24px', fontWeight: 300, letterSpacing: '-0.5px', color: T.text }}>
                    {value}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Flags */}
          {result.flags?.length > 0 && (
            <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>Flags</span>
                <span style={{ ...sx.sectionMeta, color: T.wa }}>{result.flags.length} warning{result.flags.length > 1 ? 's' : ''}</span>
              </div>
              {result.flags.map((flag: string, i: number) => (
                <div key={i} style={{
                  display: 'flex',
                  gap: '14px',
                  alignItems: 'flex-start',
                  padding: '10px 24px',
                  borderBottom: `0.5px solid ${T.borderSub}`,
                  background: `${T.wa}06`,
                }}>
                  <span style={{
                    fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px',
                    textTransform: 'uppercase', fontWeight: 500,
                    color: T.wa, background: `${T.wa}15`,
                    border: `0.5px solid ${T.wa}40`, padding: '2px 7px',
                    flexShrink: 0, marginTop: '1px',
                  }}>
                    Warn
                  </span>
                  <p style={{ fontFamily: T.sans, fontSize: '14px', color: 'rgba(16,32,51,0.68)', lineHeight: 1.6, margin: 0 }}>
                    {flag}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Top positions + Theme exposure — side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))', borderBottom: `0.5px solid ${T.border}` }}>

            {/* Top positions */}
            <div style={{ borderRight: `0.5px solid ${T.border}` }}>
              <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
                <span style={sx.sectionLabel}>Top positions</span>
                <span style={sx.sectionMeta}>Weight · Share of invested</span>
              </div>

              {/* Column headers */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '80px minmax(0,1fr) 80px 100px',
                padding: '6px 24px',
                borderBottom: `0.5px solid ${T.borderSub}`,
                background: T.sectionBg,
              }}>
                {['Ticker', 'Theme', 'Weight', 'Of invested'].map((h, i) => (
                  <span key={h} style={{
                    fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px',
                    textTransform: 'uppercase', color: T.textMuted,
                    textAlign: i >= 2 ? 'right' : 'left',
                  }}>{h}</span>
                ))}
              </div>

              {result.top_positions.map((pos: any) => (
                <div key={pos.ticker} style={{
                  display: 'grid',
                  gridTemplateColumns: '80px minmax(0,1fr) 80px 100px',
                  padding: '8px 24px',
                  borderBottom: `0.5px solid ${T.borderSub}`,
                  alignItems: 'center',
                }}>
                  <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 400, color: 'rgba(16,32,51,0.82)', letterSpacing: '0.3px' }}>
                    {pos.ticker}
                  </span>
                  <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textSub, paddingRight: '12px' }}>
                    {pos.theme || '—'}
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.text, textAlign: 'right' }}>
                    {(pos.weight * 100).toFixed(1)}%
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.textMuted, textAlign: 'right' }}>
                    {(pos.w_norm * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>

            {/* Theme exposure */}
            <div>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>Theme exposure</span>
              </div>
              {result.theme_exposure.map((t: any, i: number) => (
                <div key={t.theme} style={{
                  padding: '9px 24px',
                  borderBottom: `0.5px solid ${T.borderSub}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textSub, letterSpacing: '0.2px' }}>
                      {t.theme}
                    </span>
                    <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.text }}>
                      {(t.weight * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div style={{ height: '1px', background: 'rgba(16,32,51,0.05)' }}>
                    <div style={{
                      width: `${t.weight * 100}%`,
                      height: '100%',
                      background: T.accent,
                    }} />
                  </div>
                </div>
              ))}
            </div>

          </div>
        </>
      )}

    </main>
  );
}
