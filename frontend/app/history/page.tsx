'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ForwardReturns {
  '1d': number | null;
  '5d': number | null;
  '10d': number | null;
  '21d': number | null;
}

interface Analogue {
  date: string;
  similarity_score: number;
  score_total: number;
  confidence: number;
  environment: string;
  score_delta: number | null;
  vix_level: number | null;
  sectors_green: number | null;
  spy_close: number | null;
  score_components: Record<string, number>;
  sector_returns: Record<string, number>;
  forward_returns: ForwardReturns;
  risk_profile: { max_drawdown_5d: number | null; max_upside_5d: number | null };
  forward_path: { date: string; ret_pct: number }[];
}

interface HorizonStats {
  n: number;
  median?: number;
  pct_positive?: number;
  insufficient_data?: boolean;
  p25?: number;
  p75?: number;
  worst?: number;
  best?: number;
  distribution?: number[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const ENV_COLOR: Record<string, string> = {
  'Risk-On Rotation Day':      '#4ade80',
  'Trend Day (Directional)':   '#60a5fa',
  'Risk-Off / Headline Risk':  '#f87171',
  'Chop / Mean Reversion':     '#facc15',
  'Mixed / Neutral':           '#a78bfa',
};

const retColor = (v: number | null) => {
  if (v === null || v === undefined) return '#6b7280';
  return v >= 0 ? '#4ade80' : '#f87171';
};

const fmtRet = (v: number | null) => {
  if (v === null || v === undefined) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
};

const fmtNum = (v: number | null, d = 1) => {
  if (v === null || v === undefined) return '—';
  return v.toFixed(d);
};

// ── Mini sparkline for forward path ──────────────────────────────────────────

function Sparkline({ path }: { path: { date: string; ret_pct: number }[] }) {
  if (!path || path.length < 2) return <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>no path data</span>;
  const vals = path.map(p => p.ret_pct);
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 0);
  const range = max - min || 1;
  const W = 120; const H = 36;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x},${y}`;
  }).join(' ');
  const last = vals[vals.length - 1];
  const color = last >= 0 ? '#4ade80' : '#f87171';
  const zeroY = H - ((0 - min) / range) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '36px', maxWidth: '120px' }}>
      <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke="#333" strokeWidth="0.5" strokeDasharray="2,2" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

// ── Distribution bar chart ────────────────────────────────────────────────────

function DistributionChart({ stats, label }: { stats: HorizonStats; label: string }) {
  if (!stats?.distribution || stats.distribution.length < 3) return null;
  const vals = stats.distribution;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const W = 200; const H = 48;
  const barW = W / vals.length;

  return (
    <div>
      <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label} distribution</p>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '48px' }}>
        {vals.map((v, i) => {
          const barH = Math.max(2, ((v - min) / range) * H);
          const y = H - barH;
          const color = v >= 0 ? '#166534' : '#7f1d1d';
          return <rect key={i} x={i * barW} y={y} width={barW - 0.5} height={barH} fill={color} />;
        })}
        <line x1="0" y1={H - ((0 - min) / range) * H} x2={W} y2={H - ((0 - min) / range) * H}
          stroke="#fff" strokeWidth="0.5" opacity="0.4" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#6b7280' }}>
        <span>{min.toFixed(1)}%</span>
        <span>{max.toFixed(1)}%</span>
      </div>
    </div>
  );
}

// ── Analogue row ──────────────────────────────────────────────────────────────

function AnalogueRow({ a, isExpanded, onToggle }: {
  a: Analogue;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const fwd = a.forward_returns;
  const envColor = ENV_COLOR[a.environment] || '#9ca3af';

  return (
    <div style={{ borderTop: '1px solid #1a1a1a' }}>
      {/* Summary row */}
      <div
        onClick={onToggle}
        style={{
          display: 'grid',
          gridTemplateColumns: '100px 60px 120px 70px 70px 70px 70px 80px',
          gap: '0',
          padding: '0.625rem 1rem',
          cursor: 'pointer',
          alignItems: 'center',
          background: isExpanded ? '#111' : 'transparent',
          transition: 'background 0.1s',
        }}
      >
        <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>{a.date}</span>
        <span style={{ fontSize: '0.8125rem' }}>{a.score_total?.toFixed(0)}</span>
        <span style={{ fontSize: '0.75rem', color: envColor, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {a.environment?.split(' ')[0]}
        </span>
        <span style={{ fontSize: '0.8125rem' }}>{a.vix_level?.toFixed(1) ?? '—'}</span>
        <span style={{ fontSize: '0.8125rem', color: retColor(fwd['1d']) }}>{fmtRet(fwd['1d'])}</span>
        <span style={{ fontSize: '0.8125rem', color: retColor(fwd['5d']) }}>{fmtRet(fwd['5d'])}</span>
        <span style={{ fontSize: '0.8125rem', color: retColor(fwd['21d']) }}>{fmtRet(fwd['21d'])}</span>
        <div><Sparkline path={a.forward_path} /></div>
      </div>

      {/* Expanded detail */}
      {isExpanded && (
        <div style={{ padding: '1rem 1rem 1.25rem', background: '#0d0d0d', borderTop: '1px solid #1a1a1a' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>

            {/* State detail */}
            <div>
              <p style={{ fontSize: '0.7rem', color: '#6b7280', fontWeight: 500, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>State</p>
              {[
                ['Score', a.score_total?.toFixed(1)],
                ['Confidence', a.confidence?.toFixed(1)],
                ['Score Δ', a.score_delta ? `${a.score_delta >= 0 ? '+' : ''}${a.score_delta.toFixed(1)}` : '—'],
                ['VIX', a.vix_level?.toFixed(1)],
                ['Sectors green', a.sectors_green],
                ['SPY close', a.spy_close ? `$${a.spy_close.toFixed(2)}` : '—'],
              ].map(([label, val]) => (
                <div key={label as string} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem', padding: '3px 0', borderTop: '1px solid #1a1a1a' }}>
                  <span style={{ color: '#6b7280' }}>{label}</span>
                  <span style={{ fontWeight: 500 }}>{val ?? '—'}</span>
                </div>
              ))}
            </div>

            {/* Score components */}
            <div>
              <p style={{ fontSize: '0.7rem', color: '#6b7280', fontWeight: 500, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Score components</p>
              {Object.entries(a.score_components || {}).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '3px 0', borderTop: '1px solid #1a1a1a' }}>
                  <span style={{ fontSize: '0.75rem', color: '#6b7280', width: '120px', flexShrink: 0 }}>{k.replace(/_/g, ' ')}</span>
                  <div style={{ flex: 1, height: '4px', background: '#222', borderRadius: '2px' }}>
                    <div style={{ width: `${(v / 20) * 100}%`, height: '4px', background: v >= 12 ? '#4ade80' : v >= 8 ? '#facc15' : '#f87171', borderRadius: '2px' }} />
                  </div>
                  <span style={{ fontSize: '0.75rem', fontWeight: 500, width: '28px', textAlign: 'right' }}>{v.toFixed(1)}</span>
                </div>
              ))}
            </div>

            {/* Risk profile + forward returns detail */}
            <div>
              <p style={{ fontSize: '0.7rem', color: '#6b7280', fontWeight: 500, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Forward returns</p>
              {(['1d', '5d', '10d', '21d'] as const).map(h => (
                <div key={h} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem', padding: '3px 0', borderTop: '1px solid #1a1a1a' }}>
                  <span style={{ color: '#6b7280' }}>{h}</span>
                  <span style={{ color: retColor(fwd[h]), fontWeight: 500 }}>{fmtRet(fwd[h])}</span>
                </div>
              ))}
              <div style={{ marginTop: '12px' }}>
                <p style={{ fontSize: '0.7rem', color: '#6b7280', fontWeight: 500, margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>5-day risk</p>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem', padding: '3px 0', borderTop: '1px solid #1a1a1a' }}>
                  <span style={{ color: '#6b7280' }}>Max drawdown</span>
                  <span style={{ color: '#f87171' }}>{fmtRet(a.risk_profile.max_drawdown_5d)}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem', padding: '3px 0', borderTop: '1px solid #1a1a1a' }}>
                  <span style={{ color: '#6b7280' }}>Max upside</span>
                  <span style={{ color: '#4ade80' }}>{fmtRet(a.risk_profile.max_upside_5d)}</span>
                </div>
              </div>
            </div>

            {/* 21-day forward path chart */}
            <div>
              <p style={{ fontSize: '0.7rem', color: '#6b7280', fontWeight: 500, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>21-day path after this date</p>
              {a.forward_path.length > 1 ? (() => {
                const vals = a.forward_path.map(p => p.ret_pct);
                const min = Math.min(...vals, 0);
                const max = Math.max(...vals, 0);
                const range = max - min || 1;
                const W = 200; const H = 80;
                const pts = vals.map((v, i) => {
                  const x = (i / (vals.length - 1)) * W;
                  const y = H - ((v - min) / range) * H;
                  return `${x},${y}`;
                }).join(' ');
                const last = vals[vals.length - 1];
                const color = last >= 0 ? '#4ade80' : '#f87171';
                const zeroY = H - ((0 - min) / range) * H;
                return (
                  <div>
                    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '80px' }}>
                      <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke="#333" strokeWidth="0.5" strokeDasharray="3,3" />
                      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
                    </svg>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#6b7280' }}>
                      <span>Day 1</span>
                      <span style={{ color, fontWeight: 500 }}>Day {vals.length}: {fmtRet(last)}</span>
                    </div>
                  </div>
                );
              })() : <p style={{ fontSize: '0.75rem', color: '#4b5563' }}>No path data (recent date)</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [topN, setTopN] = useState(15);

  const { data, isLoading, error } = useSWR(
    `/api/market/analogues?top_n=${topN}`,
    fetcher,
    { refreshInterval: 300000 }
  );

  const toggle = (date: string) => setExpanded(prev => prev === date ? null : date);

  const agg = data?.aggregate_stats;
  const current = data?.current_state;

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff', background: '#0a0a0a', minHeight: '100vh' }}>

      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.25rem' }}>Market Memory</h1>
      <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '2rem' }}>
        Historical analogues — when has the market been here before, and what happened next
      </p>

      {isLoading && (
        <p style={{ color: '#6b7280' }}>Finding historical analogues...</p>
      )}
      {error && (
        <p style={{ color: '#f87171' }}>Error loading analogues. Is the backend running?</p>
      )}

      {data && (
        <>
          {/* Current state + conditions matched */}
          <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Current conditions</p>
                <p style={{ fontSize: '0.9375rem', fontWeight: 500, margin: '0 0 4px' }}>{data.conditions_matched}</p>
                <p style={{ fontSize: '0.75rem', color: '#4b5563', margin: 0 }}>
                  {current?.asof_utc?.slice(0, 10)} · score {current?.score_total?.toFixed(1)} · VIX {current?.vix_level?.toFixed(1)} · {current?.sectors_green}/11 sectors green
                </p>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>Show top</span>
                {[10, 15, 20].map(n => (
                  <button key={n} onClick={() => setTopN(n)} style={{
                    padding: '3px 10px', borderRadius: '6px', fontSize: '0.75rem',
                    border: '1px solid', borderColor: topN === n ? '#fff' : '#333',
                    background: topN === n ? '#fff' : 'transparent',
                    color: topN === n ? '#000' : '#9ca3af', cursor: 'pointer',
                  }}>{n}</button>
                ))}
              </div>
            </div>
          </div>

          {/* Aggregate stats */}
          {agg && (
            <section style={{ marginBottom: '2rem' }}>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>
                Aggregate outlook — {agg.n_analogues} comparable episodes
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
                {(['1d', '5d', '10d', '21d'] as const).map(h => {
                  const s: HorizonStats = agg.forward_returns[h];
                  if (!s || s.insufficient_data) return null;
                  const isPos = (s.median ?? 0) >= 0;
                  return (
                    <div key={h} style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem' }}>
                      <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h} forward</p>
                      <p style={{ fontSize: '1.5rem', fontWeight: 600, margin: '0 0 2px', color: isPos ? '#4ade80' : '#f87171' }}>
                        {s.median !== undefined ? `${s.median >= 0 ? '+' : ''}${s.median.toFixed(2)}%` : '—'}
                      </p>
                      <p style={{ fontSize: '0.8125rem', color: '#9ca3af', margin: '0 0 8px' }}>
                        {s.pct_positive?.toFixed(0)}% positive · n={s.n}
                      </p>
                      <div style={{ display: 'flex', gap: '1rem', fontSize: '0.75rem' }}>
                        <span style={{ color: '#f87171' }}>p25: {s.p25?.toFixed(2)}%</span>
                        <span style={{ color: '#4ade80' }}>p75: {s.p75?.toFixed(2)}%</span>
                      </div>
                      <div style={{ marginTop: '8px' }}>
                        <DistributionChart stats={s} label={h} />
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Risk profile aggregate */}
              {agg.risk_profile && (
                <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem 1.25rem' }}>
                  <p style={{ fontSize: '0.75rem', color: '#6b7280', fontWeight: 500, margin: '0 0 10px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>5-day risk profile</p>
                  <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
                    <div>
                      <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Median max drawdown</p>
                      <p style={{ fontSize: '1.125rem', fontWeight: 600, color: '#f87171', margin: 0 }}>{agg.risk_profile.median_max_drawdown_5d?.toFixed(2)}%</p>
                    </div>
                    <div>
                      <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Median max upside</p>
                      <p style={{ fontSize: '1.125rem', fontWeight: 600, color: '#4ade80', margin: 0 }}>+{agg.risk_profile.median_max_upside_5d?.toFixed(2)}%</p>
                    </div>
                    {agg.risk_profile.reward_risk_ratio && (
                      <div>
                        <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Reward / risk</p>
                        <p style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>{agg.risk_profile.reward_risk_ratio?.toFixed(1)}x</p>
                      </div>
                    )}
                    <div>
                      <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Worst 5d case</p>
                      <p style={{ fontSize: '1.125rem', fontWeight: 600, color: '#f87171', margin: 0 }}>{agg.risk_profile.worst_drawdown_5d?.toFixed(2)}%</p>
                    </div>
                    <div>
                      <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 2px' }}>Best 5d case</p>
                      <p style={{ fontSize: '1.125rem', fontWeight: 600, color: '#4ade80', margin: 0 }}>+{agg.risk_profile.best_upside_5d?.toFixed(2)}%</p>
                    </div>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Analogues table */}
          <section>
            <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>
              Comparable episodes — click any row to expand
            </h2>
            <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', overflow: 'hidden' }}>
              {/* Header */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '100px 60px 120px 70px 70px 70px 70px 80px',
                gap: '0',
                padding: '0.625rem 1rem',
                borderBottom: '1px solid #222',
              }}>
                {['Date', 'Score', 'Environment', 'VIX', '1d fwd', '5d fwd', '21d fwd', '21d path'].map(h => (
                  <span key={h} style={{ fontSize: '0.7rem', fontWeight: 500, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</span>
                ))}
              </div>

              {/* Rows */}
              {data.analogues?.map((a: Analogue) => (
                <AnalogueRow
                  key={a.date}
                  a={a}
                  isExpanded={expanded === a.date}
                  onToggle={() => toggle(a.date)}
                />
              ))}
            </div>
            <p style={{ fontSize: '0.75rem', color: '#4b5563', marginTop: '0.75rem' }}>
              Analogues ranked by similarity to current conditions (environment + score range + VIX regime + breadth + score momentum).
              Click any row to see the full state detail and 21-day forward price path.
            </p>
          </section>
        </>
      )}
    </main>
  );
}
