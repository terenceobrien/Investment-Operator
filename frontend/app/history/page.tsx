'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import NarrativeTab from '../../components/NarrativeTab';
import { SkeletonBlock, SkeletonRows } from '@/components/Skeleton';
import { T, sx, formatAccountingPct, formatCurrency, formatNumber } from '@/lib/tokens';

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
  has_narrative?: boolean;
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
  'Risk-On Rotation Day':     T.up,
  'Trend Day (Directional)':  '#60a5fa',
  'Risk-Off / Headline Risk': T.dn,
  'Chop / Mean Reversion':    T.wa,
  'Mixed / Neutral':          T.accent,
};

const fmtRet = (v: number | null) => {
  if (v === null || v === undefined) return '—';
  return formatAccountingPct(v);
};

const retColor = (v: number | null) => {
  if (v === null || v === undefined) return T.mid;
  return v >= 0 ? T.up : T.dn;
};

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ path }: { path: { date: string; ret_pct: number }[] }) {
  if (!path || path.length < 2) {
    return <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>—</span>;
  }
  const vals  = path.map(p => p.ret_pct);
  const min   = Math.min(...vals, 0);
  const max   = Math.max(...vals, 0);
  const range = max - min || 1;
  const W = 80; const H = 28;
  const pts   = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x},${y}`;
  }).join(' ');
  const last  = vals[vals.length - 1];
  const color = last >= 0 ? T.up : T.dn;
  const zeroY = H - ((0 - min) / range) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '80px', height: '28px' }}>
      <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke={T.borderSub} strokeWidth="0.5" strokeDasharray="2,2" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1" />
    </svg>
  );
}

// ── Distribution mini-chart ───────────────────────────────────────────────────

function DistributionChart({ stats }: { stats: HorizonStats }) {
  if (!stats?.distribution || stats.distribution.length < 3) return null;
  const vals  = stats.distribution;
  const min   = Math.min(...vals);
  const max   = Math.max(...vals);
  const range = max - min || 1;
  const W = 160; const H = 32;
  const barW  = W / vals.length;
  const zeroY = H - ((0 - min) / range) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '32px' }}>
      {vals.map((v, i) => {
        const barH = Math.max(1, ((Math.abs(v - min)) / range) * H);
        const y    = H - barH;
        const fill = v >= 0 ? 'rgba(87,160,106,0.5)' : 'rgba(184,85,85,0.5)';
        return <rect key={i} x={i * barW} y={y} width={barW - 0.5} height={barH} fill={fill} />;
      })}
      <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke="rgba(255,255,255,0.12)" strokeWidth="0.5" />
    </svg>
  );
}

// ── Aggregate forward card ────────────────────────────────────────────────────

function FwdCard({ horizon, stats }: { horizon: string; stats: HorizonStats }) {
  if (!stats || stats.insufficient_data) return null;
  const isPos = (stats.median ?? 0) >= 0;
  const c     = isPos ? T.up : T.dn;
  return (
    <div style={{ padding: '14px 20px', borderRight: `0.5px solid ${T.border}` }}>
      <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
        {horizon} forward
      </div>
      <div style={{ fontFamily: T.mono, fontSize: '22px', fontWeight: 300, letterSpacing: '-0.5px', color: c, marginBottom: '4px' }}>
        {stats.median !== undefined ? fmtRet(stats.median) : '—'}
      </div>
      <div style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted, marginBottom: '10px' }}>
        {stats.pct_positive?.toFixed(0)}% positive · n={stats.n}
      </div>
      <div style={{ display: 'flex', gap: '10px', marginBottom: '8px' }}>
        <span style={{ fontFamily: T.mono, fontSize: '11.5px', fontWeight: 300, color: T.dn }}>p25: {stats.p25?.toFixed(2)}%</span>
        <span style={{ fontFamily: T.mono, fontSize: '11.5px', fontWeight: 300, color: T.up }}>p75: {stats.p75?.toFixed(2)}%</span>
      </div>
      <DistributionChart stats={stats} />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '2px' }}>
        <span style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color: T.textMuted }}>{Math.min(...(stats.distribution ?? [0])).toFixed(1)}%</span>
        <span style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color: T.textMuted }}>{Math.max(...(stats.distribution ?? [0])).toFixed(1)}%</span>
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
  const fwd      = a.forward_returns;
  const envColor = ENV_COLOR[a.environment] || T.mid;

  return (
    <div style={{ borderBottom: `0.5px solid ${T.borderSub}` }}>

      {/* Summary row */}
      <div
        className="temper-interactive-row"
        onClick={onToggle}
        style={{
          display: 'grid',
          gridTemplateColumns: '90px 52px 130px 60px 72px 72px 72px 90px',
          alignItems: 'center',
          padding: '8px 24px',
          cursor: 'pointer',
          background: isExpanded ? 'rgba(255,255,255,0.025)' : 'transparent',
        }}
      >
        <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: 'rgba(255,255,255,0.78)', letterSpacing: '0.2px' }}>
          {a.date}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.textSub }}>
          {a.score_total?.toFixed(0)}
        </span>
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: envColor, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {a.environment?.split(' / ')[0] ?? a.environment}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: T.textSub }}>
          {a.vix_level?.toFixed(1) ?? '—'}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: retColor(fwd['1d']) }}>
          {fmtRet(fwd['1d'])}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: retColor(fwd['5d']) }}>
          {fmtRet(fwd['5d'])}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: retColor(fwd['21d']) }}>
          {fmtRet(fwd['21d'])}
        </span>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Sparkline path={a.forward_path} />
        </div>
      </div>

      {/* Expanded detail */}
      {isExpanded && (
          <div style={{ background: 'rgba(255,255,255,0.012)', borderTop: `0.5px solid ${T.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))' }}>

            {/* State */}
            <div style={{ padding: '14px 20px', borderRight: `0.5px solid ${T.border}` }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                State
              </div>
              {[
                ['Score',      a.score_total?.toFixed(1)],
                ['Confidence', a.confidence?.toFixed(1)],
                ['Score Δ',    a.score_delta != null ? (a.score_delta >= 0 ? '+' : '') + a.score_delta.toFixed(1) : '—'],
                ['VIX',        a.vix_level?.toFixed(1) ?? '—'],
                ['Breadth',    a.sectors_green != null ? `${a.sectors_green}/11` : '—'],
                ['SPY close',  a.spy_close != null ? formatCurrency(a.spy_close) : '—'],
              ].map(([label, val]) => (
                <div key={label as string} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: `0.5px solid ${T.borderSub}` }}>
                  <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>{label}</span>
                  <span style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: 'rgba(255,255,255,0.75)' }}>{val}</span>
                </div>
              ))}
            </div>

            {/* Score components */}
            <div style={{ padding: '14px 20px', borderRight: `0.5px solid ${T.border}` }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                Score components
              </div>
              {Object.entries(a.score_components ?? {}).map(([k, v]) => {
                const fill = v >= 6 ? T.up : v >= 4 ? T.wa : T.dn;
                return (
                  <div key={k} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0', borderBottom: `0.5px solid ${T.borderSub}` }}>
                    <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted, width: '110px', flexShrink: 0 }}>
                      {k.replace(/_/g, ' ')}
                    </span>
                    <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.05)' }}>
                      <div style={{ width: `${(v / 10) * 100}%`, height: '100%', background: fill }} />
                    </div>
                    <span style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: fill, width: '24px', textAlign: 'right' }}>
                      {v?.toFixed(1)}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Sector returns */}
            <div style={{ padding: '14px 20px', borderRight: `0.5px solid ${T.border}` }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                Sector returns
              </div>
              {Object.entries(a.sector_returns ?? {})
                .sort((x, y) => (y[1] as number) - (x[1] as number))
                .map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: `0.5px solid ${T.borderSub}` }}>
                    <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>{k}</span>
                    <span style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: (v as number) >= 0 ? T.up : T.dn }}>
                      {fmtRet(v as number)}
                    </span>
                  </div>
                ))}
            </div>

            {/* Forward path */}
            <div style={{ padding: '14px 20px' }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                21-day forward path
              </div>
              {a.forward_path && a.forward_path.length >= 2 ? (() => {
                const vals  = a.forward_path.map(p => p.ret_pct);
                const min   = Math.min(...vals, 0);
                const max   = Math.max(...vals, 0);
                const range = max - min || 1;
                const W = 200; const H = 80;
                const pts   = vals.map((v, i) => {
                  const x = (i / (vals.length - 1)) * W;
                  const y = H - ((v - min) / range) * H * 0.85 - H * 0.075;
                  return `${x},${y}`;
                }).join(' ');
                const last  = vals[vals.length - 1];
                const color = last >= 0 ? T.up : T.dn;
                const zeroY = H - ((0 - min) / range) * H * 0.85 - H * 0.075;
                return (
                  <div>
                    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '80px' }}>
                      <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" strokeDasharray="3,3" />
                      <polyline points={pts} fill="none" stroke={color} strokeWidth="1" />
                    </svg>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px' }}>
                      <span style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color: T.textMuted }}>Day 1</span>
                      <span style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color }}>Day {vals.length}: {fmtRet(last)}</span>
                    </div>
                    {/* Risk profile */}
                    <div style={{ display: 'flex', gap: '16px', marginTop: '12px', paddingTop: '10px', borderTop: `0.5px solid ${T.borderSub}` }}>
                      <div>
                        <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '3px' }}>Max DD</div>
                        <div style={{ fontFamily: T.mono, fontSize: '14px', fontWeight: 300, color: T.dn }}>{fmtRet(a.risk_profile?.max_drawdown_5d)}</div>
                      </div>
                      <div>
                        <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '3px' }}>Max up</div>
                        <div style={{ fontFamily: T.mono, fontSize: '14px', fontWeight: 300, color: T.up }}>{fmtRet(a.risk_profile?.max_upside_5d)}</div>
                      </div>
                    </div>
                  </div>
                );
              })() : (
                <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.textMuted }}>No path data</span>
              )}

              {/* Narrative tab */}
              <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: `0.5px solid ${T.borderSub}` }}>
                <NarrativeTab date={a.date} hasSnapshot={a.has_narrative || false} />
              </div>
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
  const [topN,     setTopN]     = useState(15);

  const { data, isLoading, error } = useSWR(
    `/api/market/analogues?top_n=${topN}`,
    fetcher,
    { refreshInterval: 300000 }
  );

  const toggle  = (date: string) => setExpanded(prev => prev === date ? null : date);
  const agg     = data?.aggregate_stats;
  const current = data?.current_state;

  return (
    <main style={sx.main}>

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
          <span style={sx.sectionLabel}>Market memory</span>
          <span style={sx.sectionMeta}>Historical analogues · when has the market been here before</span>
        </div>
      </div>

      {isLoading && (
        <div style={{ padding: '24px 0' }}>
          <div style={{ padding: '0 24px 18px' }}>
            <SkeletonBlock width="34%" height={12} style={{ marginBottom: '10px' }} />
            <SkeletonBlock width="52%" height={12} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', borderTop: `0.5px solid ${T.border}` }}>
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} style={{ padding: '14px 20px', borderRight: `0.5px solid ${T.border}` }}>
                <SkeletonBlock width="42%" height={10} style={{ marginBottom: '10px' }} />
                <SkeletonBlock width="58%" height={20} style={{ marginBottom: '10px' }} />
                <SkeletonBlock width="72%" height={10} />
              </div>
            ))}
          </div>
          <SkeletonRows rows={8} columns={4} />
        </div>
      )}
      {error && (
        <div style={{ padding: '40px 24px' }}>
          <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.dn }}>Error loading analogues.</span>
        </div>
      )}

      {data && (
        <>
          {/* ── Current conditions ─────────────────────────────────────── */}
          <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
            <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Current conditions</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', color: T.textMuted }}>Show top</span>
                {[10, 15, 20].map(n => (
                  <button
                    key={n}
                    onClick={() => setTopN(n)}
                    style={{
                      fontFamily: T.mono,
                      fontSize: '12px',
                      fontWeight: 300,
                      color: topN === n ? 'rgba(255,255,255,0.9)' : T.textMuted,
                      background: topN === n ? 'rgba(255,255,255,0.06)' : 'transparent',
                      border: `0.5px solid ${topN === n ? 'rgba(255,255,255,0.15)' : T.border}`,
                      padding: '2px 9px',
                      cursor: 'pointer',
                    }}
                  >{n}</button>
                ))}
              </div>
            </div>
            <div style={{ padding: '12px 24px' }}>
              <div style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: 'rgba(255,255,255,0.75)', letterSpacing: '0.3px', marginBottom: '4px' }}>
                {data.conditions_matched}
              </div>
              <div style={{ fontFamily: T.mono, fontSize: '11.5px', fontWeight: 300, color: T.textMuted }}>
                {current?.asof_utc?.slice(0, 10)} · score {formatNumber(current?.score_total, 1)} · VIX {formatNumber(current?.vix_level, 1)} · {current?.sectors_green}/11 sectors green
              </div>
            </div>
          </div>

          {/* ── Aggregate outlook ──────────────────────────────────────── */}
          {agg && (
            <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>Aggregate outlook</span>
                <span style={sx.sectionMeta}>{agg.n_analogues} comparable episodes</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', borderBottom: `0.5px solid ${T.border}` }}>
                {(['1d', '5d', '10d', '21d'] as const).map(h => (
                  <FwdCard key={h} horizon={h} stats={agg.forward_returns[h]} />
                ))}
              </div>

              {/* Risk profile */}
              {agg.risk_profile && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
                  {[
                    { label: '5D risk profile', val: null },
                    { label: 'Median max DD',     val: agg.risk_profile.median_max_drawdown_5d,  color: T.dn, fmt: fmtRet },
                    { label: 'Median max upside', val: agg.risk_profile.median_max_upside_5d,    color: T.up, fmt: (v: number) => formatAccountingPct(v) },
                    { label: 'Reward / risk',     val: agg.risk_profile.reward_risk_ratio,        color: T.mid, fmt: (v: number) => `${v.toFixed(1)}×` },
                    { label: 'Worst 5D',          val: agg.risk_profile.worst_drawdown_5d,        color: T.dn, fmt: fmtRet },
                  ].map(({ label, val, color, fmt }, i) => (
                    <div key={label} style={{ padding: '12px 20px', borderRight: i < 4 ? `0.5px solid ${T.border}` : 'none' }}>
                      <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '5px' }}>
                        {label}
                      </div>
                      {val !== null && val !== undefined && fmt && (
                        <div style={{ fontFamily: T.mono, fontSize: '17px', fontWeight: 300, color: color ?? T.text }}>
                          {fmt(val)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Analogues table ────────────────────────────────────────── */}
          <div>
            <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Comparable episodes</span>
              <span style={sx.sectionMeta}>Click any row to expand</span>
            </div>

            {/* Table header */}
            <div style={{ overflowX: 'auto' }}>
              <div style={{ minWidth: '640px' }}>
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '90px 52px 130px 60px 72px 72px 72px 90px',
                  padding: '6px 24px',
                  borderBottom: `0.5px solid ${T.border}`,
                  background: T.sectionBg,
                }}>
                  {['Date', 'Score', 'Environment', 'VIX', '1D fwd', '5D fwd', '21D fwd', '21D path'].map(h => (
                    <span key={h} style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted }}>
                      {h}
                    </span>
                  ))}
                </div>

                {data.analogues?.map((a: Analogue) => (
                  <AnalogueRow
                    key={a.date}
                    a={a}
                    isExpanded={expanded === a.date}
                    onToggle={() => toggle(a.date)}
                  />
                ))}
              </div>
            </div>

            <div style={{ padding: '12px 24px', borderTop: `0.5px solid ${T.borderSub}` }}>
              <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted, lineHeight: 1.5 }}>
                Analogues ranked by similarity to current conditions (environment + score range + VIX regime + breadth + score momentum).
              </span>
            </div>
          </div>
        </>
      )}

    </main>
  );
}
