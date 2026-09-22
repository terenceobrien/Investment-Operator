'use client';

import { useState, useRef } from 'react';
import { useAuth } from '@clerk/nextjs';
import AuthRequired from '@/components/AuthRequired';
import { SkeletonBlock } from '@/components/Skeleton';
import { T, sx } from '@/lib/tokens';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? '';

interface PortfolioSummary {
  n_positions: number;
  cash_weight: number;
  top1_invested: number;
  top3_invested: number;
  top5_invested: number;
}

interface TopPosition {
  ticker: string;
  weight: number;
  theme?: string;
  w_norm: number;
}

interface ThemeExposure {
  theme: string;
  weight: number;
}

interface RegimeAlignment {
  score: number;
  aligned_weight: number;
  misaligned_weight: number;
  unknown_weight: number;
  cash_like_weight: number;
  main_mismatch: string;
}

interface ExposureMapItem {
  name: string;
  current_weight: number;
  target_min?: number;
  target_max?: number;
  target_range?: string;
  gap_to_min?: number;
  status: 'underweight' | 'in_range' | 'neutral' | 'overweight';
}

interface PositionDiagnostic {
  ticker: string;
  weight: number;
  regime_score: number;
  action: string;
  reason: string;
  tags: string[];
}

interface SuggestedBucket {
  bucket?: string;
  name: string;
  current_weight: number;
  target_min?: number;
  target_max?: number;
  target_range: string;
  gap_to_min?: number;
  examples: string[];
  why_it_fits: string;
  type: string;
  status: 'underweight' | 'in_range' | 'neutral' | 'overweight';
}

interface KeyDriver {
  name: string;
  status: string;
  explanation: string;
}

interface ContextPanel {
  title: string;
  regime_headline: string;
  regime_summary: string;
  risk_summary: string;
  key_drivers: KeyDriver[];
  portfolio_implications: string[];
  best_positioned: string[];
  most_vulnerable: string[];
}

interface DiagnosisSummary {
  headline: string;
  bullets: string[];
}

interface RegimeOverlay {
  regime: {
    label: string;
    confidence: number;
  };
  context_panel?: ContextPanel;
  diagnosis_summary?: DiagnosisSummary;
  alignment: RegimeAlignment;
  exposure_map: ExposureMapItem[];
  position_diagnostics: PositionDiagnostic[];
  suggested_buckets: SuggestedBucket[];
  falsifiers: string[];
}

interface PortfolioResult {
  summary: PortfolioSummary;
  top_positions: TopPosition[];
  theme_exposure: ThemeExposure[];
  flags: string[];
  regime_overlay?: RegimeOverlay | null;
}

function pct(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(decimals)}%`;
}

function scoreColor(score: number): string {
  if (score >= 75) return T.up;
  if (score >= 55) return T.accentDark;
  if (score >= 35) return T.wa;
  return T.dn;
}

function statusColor(status: ExposureMapItem['status']): string {
  if (status === 'underweight') return T.wa;
  if (status === 'overweight') return T.dn;
  return T.up;
}

function statusLabel(status: ExposureMapItem['status']): string {
  return status === 'in_range' ? 'in range' : status;
}

function RegimeOverlaySection({ overlay }: { overlay: RegimeOverlay }) {
  const context = overlay.context_panel;
  const diagnosis = overlay.diagnosis_summary;
  return (
    <>
      {context ? (
        <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
          <div style={sx.sectionHd}>
            <span style={sx.sectionLabel}>Macro context</span>
            <span style={sx.sectionMeta}>{context.title}</span>
          </div>
          <div style={{ padding: '22px 24px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '22px' }}>
            <div>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '8px' }}>
                {overlay.regime.label}
              </div>
              <h2 style={{ margin: 0, fontFamily: T.sans, fontSize: '22px', lineHeight: 1.2, letterSpacing: '-0.03em', color: T.navy, fontWeight: 650 }}>
                {context.regime_headline}
              </h2>
              <p style={{ margin: '12px 0 0', fontFamily: T.sans, fontSize: '14px', lineHeight: 1.6, color: T.textSub }}>
                {context.regime_summary}
              </p>
              <div style={{ marginTop: '14px', padding: '13px 14px', border: `1px solid ${T.borderSub}`, background: T.surfaceMuted, borderRadius: '12px' }}>
                <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                  Risk summary
                </div>
                <div style={{ fontFamily: T.sans, fontSize: '13px', lineHeight: 1.55, color: T.text }}>
                  {context.risk_summary}
                </div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '12px' }}>
              <div style={{ ...sx.subPanel, padding: '14px' }}>
                <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
                  Confidence
                </div>
                <div style={{ fontFamily: T.mono, fontSize: '24px', color: T.navy, fontWeight: 300 }}>{pct(overlay.regime.confidence, 0)}</div>
              </div>
              <div style={{ ...sx.subPanel, padding: '14px' }}>
                <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
                  Best positioned
                </div>
                <div style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.5 }}>
                  {(context.best_positioned ?? []).join(' · ')}
                </div>
              </div>
              <div style={{ ...sx.subPanel, padding: '14px' }}>
                <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
                  Most vulnerable
                </div>
                <div style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.5 }}>
                  {(context.most_vulnerable ?? []).join(' · ')}
                </div>
              </div>
              <div style={{ ...sx.subPanel, padding: '14px' }}>
                <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
                  Portfolio implication
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {(context.portfolio_implications ?? []).map((item) => (
                    <div key={item} style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.45 }}>
                      <span style={{ color: T.accentDark, fontWeight: 700 }}>• </span>{item}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))', borderTop: `0.5px solid ${T.borderSub}` }}>
            {(context.key_drivers ?? []).map((driver) => (
              <div key={driver.name} style={{ padding: '14px 18px', borderRight: `0.5px solid ${T.borderSub}` }}>
                <div style={{ fontFamily: T.sans, fontSize: '13px', color: T.text, fontWeight: 650, marginBottom: '4px' }}>{driver.name}</div>
                <div style={{ fontFamily: T.sans, fontSize: '11px', color: T.accentDark, fontWeight: 650, marginBottom: '7px' }}>{driver.status}</div>
                <div style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.5 }}>{driver.explanation}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Regime alignment</span>
          <span style={sx.sectionMeta}>{overlay.regime.label}</span>
        </div>
        <div style={{ padding: '18px 24px', borderBottom: `0.5px solid ${T.borderSub}` }}>
          <div style={{ fontFamily: T.sans, fontSize: '16px', color: T.navy, fontWeight: 650, lineHeight: 1.35, marginBottom: '10px' }}>
            {diagnosis?.headline ?? overlay.alignment.main_mismatch}
          </div>
          {diagnosis?.bullets?.length ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '8px 18px' }}>
              {diagnosis.bullets.map((bullet) => (
                <div key={bullet} style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.5 }}>
                  <span style={{ color: T.accentDark, fontWeight: 700 }}>• </span>{bullet}
                </div>
              ))}
            </div>
          ) : null}
          <div style={{ marginTop: '12px', fontFamily: T.sans, fontSize: '13px', color: T.text, lineHeight: 1.5 }}>
            <strong>Main mismatch:</strong> {overlay.alignment.main_mismatch}
          </div>
          {overlay.alignment.unknown_weight > 0 ? (
            <div style={{ marginTop: '10px', padding: '8px 10px', border: `1px solid ${T.wa}40`, background: `${T.wa}08`, color: T.wa, fontFamily: T.sans, fontSize: '12px' }}>
              Data quality warning: {pct(overlay.alignment.unknown_weight)} of the portfolio has no overlay metadata yet.
            </div>
          ) : null}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
          <div style={{ padding: '16px 24px', borderRight: `0.5px solid ${T.border}` }}>
            <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '8px' }}>
              Alignment score
            </div>
            <div style={{ fontFamily: T.mono, fontSize: '23px', fontWeight: 300, letterSpacing: '-0.5px', color: scoreColor(overlay.alignment.score) }}>
              {overlay.alignment.score.toFixed(1)}
            </div>
          </div>
          {[
            { label: 'Aligned weight', value: pct(overlay.alignment.aligned_weight), color: T.up },
            { label: 'Misaligned weight', value: pct(overlay.alignment.misaligned_weight), color: T.dn },
            { label: 'Cash-like', value: pct(overlay.alignment.cash_like_weight), color: T.accentDark },
          ].map((item) => (
            <div key={item.label} style={{ padding: '16px 24px', borderRight: `0.5px solid ${T.border}` }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '8px' }}>
                {item.label}
              </div>
              <div style={{ fontFamily: T.mono, fontSize: '23px', fontWeight: 300, letterSpacing: '-0.5px', color: item.color }}>
                {item.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px,1fr))', borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ borderRight: `0.5px solid ${T.border}` }}>
          <div style={sx.sectionHd}>
            <span style={sx.sectionLabel}>Exposure map</span>
          </div>
          {overlay.exposure_map.map((item) => (
            <div key={item.name} style={{ padding: '10px 24px', borderBottom: `0.5px solid ${T.borderSub}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub }}>{item.name}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12.5px', color: T.text }}>
                  {pct(item.current_weight)}{item.target_range ? ` / ${item.target_range}` : ''}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ flex: 1, height: '2px', background: 'rgba(16,32,51,0.06)' }}>
                  <div style={{ width: `${Math.min(item.current_weight * 100, 100)}%`, height: '100%', background: statusColor(item.status) }} />
                </div>
                <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: statusColor(item.status), minWidth: '86px', textAlign: 'right' }}>
                  {statusLabel(item.status)}
                </span>
              </div>
            </div>
          ))}
        </div>

        <div>
          <div style={sx.sectionHd}>
            <span style={sx.sectionLabel}>Falsifiers</span>
          </div>
          {overlay.falsifiers.map((falsifier) => (
            <div key={falsifier} style={{ padding: '11px 24px', borderBottom: `0.5px solid ${T.borderSub}` }}>
              <span style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.5 }}>{falsifier}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Position diagnostics</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ minWidth: '760px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '90px 90px 120px 170px minmax(260px,1fr)', padding: '8px 24px', borderBottom: `0.5px solid ${T.borderSub}`, background: T.sectionBg }}>
              {['Ticker', 'Weight', 'Regime score', 'Action', 'Reason'].map((h) => (
                <span key={h} style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted }}>{h}</span>
              ))}
            </div>
            {overlay.position_diagnostics.map((pos) => (
              <div key={pos.ticker} style={{ display: 'grid', gridTemplateColumns: '90px 90px 120px 170px minmax(260px,1fr)', padding: '10px 24px', borderBottom: `0.5px solid ${T.borderSub}`, alignItems: 'center' }}>
                <span style={{ fontFamily: T.mono, fontSize: '13px', color: T.text }}>{pos.ticker}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12.5px', color: T.textMuted }}>{pct(pos.weight)}</span>
                <span style={{ fontFamily: T.mono, fontSize: '13px', color: scoreColor(pos.regime_score) }}>{pos.regime_score}</span>
                <span style={{ fontFamily: T.sans, fontSize: '12.5px', color: scoreColor(pos.regime_score), fontWeight: 600 }}>{pos.action}</span>
                <span style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.45 }}>{pos.reason}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Suggested buckets</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ minWidth: '860px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '180px 110px 110px 100px 100px 220px minmax(240px,1fr)', padding: '8px 24px', borderBottom: `0.5px solid ${T.borderSub}`, background: T.sectionBg }}>
              {['Bucket', 'Current', 'Target', 'Gap to min', 'Status', 'Examples', 'Why it fits'].map((h) => (
                <span key={h} style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted }}>{h}</span>
              ))}
            </div>
            {overlay.suggested_buckets.map((bucket) => (
              <div key={bucket.name} style={{ display: 'grid', gridTemplateColumns: '180px 110px 110px 100px 100px 220px minmax(240px,1fr)', padding: '11px 24px', borderBottom: `0.5px solid ${T.borderSub}`, alignItems: 'start' }}>
                <span style={{ fontFamily: T.sans, fontSize: '13px', color: T.text, fontWeight: 600 }}>{bucket.bucket ?? bucket.name}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12.5px', color: statusColor(bucket.status) }}>{pct(bucket.current_weight)}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12.5px', color: T.text }}>{bucket.target_range}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12.5px', color: (bucket.gap_to_min ?? 0) > 0 ? T.wa : T.textMuted }}>{pct(bucket.gap_to_min ?? 0)}</span>
                <span style={{ fontFamily: T.sans, fontSize: '11px', color: statusColor(bucket.status), textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 650 }}>{statusLabel(bucket.status)}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>{bucket.examples.join(', ')}</span>
                <span style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.45 }}>{bucket.why_it_fits}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

export default function PortfolioPage() {
  const [result,   setResult]   = useState<PortfolioResult | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const { getToken, isLoaded, isSignedIn } = useAuth();

  const analyze = async (file: File) => {
    if (!isLoaded || !isSignedIn) {
      setError('Sign-in required');
      return;
    }
    setLoading(true);
    setError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const token = await getToken();
      const res = await fetch(`${BACKEND_URL}/api/portfolio/analyze`, {
        method: 'POST',
        body: form,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      setResult(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Portfolio analysis failed');
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

  if (!isLoaded || !isSignedIn) {
    return <AuthRequired isLoaded={isLoaded} />;
  }

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

          {result.regime_overlay ? (
            <RegimeOverlaySection overlay={result.regime_overlay} />
          ) : null}

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

              {result.top_positions.map((pos) => (
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
              {result.theme_exposure.map((t) => (
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
