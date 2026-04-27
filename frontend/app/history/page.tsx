'use client';

import { MouseEvent, useState } from 'react';
import useSWR from 'swr';
import { useAuthFetcher } from '../../lib/api';
import { SkeletonBlock, SkeletonRows, SkeletonText } from '@/components/Skeleton';
import { T, sx, formatAccountingPct, formatCurrency, formatNumber } from '@/lib/tokens';

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

interface NarrativeData {
  date: string;
  narrative: {
    summary: string;
    key_signals: string[];
    risks_and_uncertainties: string[];
    regime_verdict: string;
    outcome_note: string;
  };
  generated: boolean;
  model: string;
}

const ENV_COLOR: Record<string, string> = {
  'Risk-On Rotation Day': T.up,
  'Trend Day (Directional)': '#60a5fa',
  'Risk-Off / Headline Risk': T.dn,
  'Chop / Mean Reversion': T.wa,
  'Mixed / Neutral': T.accent,
};

const fmtRet = (v: number | null) => {
  if (v === null || v === undefined) return '—';
  return formatAccountingPct(v);
};

const retColor = (v: number | null) => {
  if (v === null || v === undefined) return T.mid;
  return v >= 0 ? T.up : T.dn;
};

const formatDayNumber = (day: number) => String(day);

function getEvenTicks(totalDays: number, count: number) {
  if (totalDays <= 1) return [1];
  const ticks = new Set<number>();
  for (let i = 0; i < count; i += 1) {
    const day = 1 + Math.round((i * (totalDays - 1)) / Math.max(1, count - 1));
    ticks.add(day);
  }
  ticks.add(1);
  ticks.add(totalDays);
  return Array.from(ticks).sort((a, b) => a - b);
}

function DistributionChart({ stats }: { stats: HorizonStats }) {
  if (!stats?.distribution || stats.distribution.length < 3) return null;
  const vals = stats.distribution;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const W = 160;
  const H = 32;
  const barW = W / vals.length;
  const zeroY = H - ((0 - min) / range) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '32px' }}>
      {vals.map((v, i) => {
        const barH = Math.max(1, (Math.abs(v - min) / range) * H);
        const y = H - barH;
        const fill = v >= 0 ? 'rgba(87,160,106,0.5)' : 'rgba(184,85,85,0.5)';
        return <rect key={i} x={i * barW} y={y} width={barW - 0.5} height={barH} fill={fill} />;
      })}
      <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke="rgba(255,255,255,0.12)" strokeWidth="0.5" />
    </svg>
  );
}

function FwdCard({ horizon, stats }: { horizon: string; stats: HorizonStats }) {
  if (!stats || stats.insufficient_data) return null;
  const isPos = (stats.median ?? 0) >= 0;
  const c = isPos ? T.up : T.dn;
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

function HistoricalPathChart({ analogue }: { analogue: Analogue }) {
  const path = analogue.forward_path ?? [];
  const [hoverState, setHoverState] = useState<{ x: number; value: number; day: number; date: Date } | null>(null);
  if (path.length < 2) {
    return <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.textMuted }}>No path data</span>;
  }

  const vals = path.map((p) => p.ret_pct ?? 0);
  const totalDays = Math.max(21, path.length);
  const maxAbsObserved = Math.max(...vals.map((v) => Math.abs(v)), 0);
  const yBound = Math.max(10, Math.ceil(maxAbsObserved));
  const W = 520;
  const H = 238;
  const padL = 18;
  const padR = 58;
  const padT = 14;
  const padB = 34;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const lineColor = vals[vals.length - 1] >= 0 ? T.up : T.dn;

  const xForDay = (day: number) => padL + ((day - 1) / Math.max(1, totalDays - 1)) * innerW;
  const yForValue = (value: number) => padT + ((yBound - value) / (2 * yBound)) * innerH;
  const points = vals.map((value, idx) => `${xForDay(idx + 1)},${yForValue(value)}`).join(' ');
  const yTicks = [-yBound, -yBound / 2, 0, yBound / 2, yBound];
  const xTicks = getEvenTicks(21, 6);
  const hoveredValue = hoverState?.value ?? 0;
  const hoveredX = hoverState?.x ?? null;
  const hoveredY = hoverState ? yForValue(hoverState.value) : null;
  const hoveredColor = retColor(hoveredValue);
  const hoveredDay = hoverState ? Math.max(1, Math.min(totalDays, Math.round(hoverState.day))) : null;
  const nearestPoint = hoveredDay ? path[Math.min(path.length - 1, hoveredDay - 1)] : null;
  const hoverDateLabel = nearestPoint
    ? new Intl.DateTimeFormat('en-US', {
        month: '2-digit',
        day: '2-digit',
        year: '2-digit',
      }).format(new Date(nearestPoint.date))
    : '';

  const onMouseMove = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = ((event.clientX - rect.left) / rect.width) * W;
    const clampedX = Math.min(W - padR, Math.max(padL, relativeX));
    const ratio = (clampedX - padL) / Math.max(innerW, 1);
    const floatIndex = ratio * Math.max(path.length - 1, 1);
    const leftIndex = Math.floor(floatIndex);
    const rightIndex = Math.min(path.length - 1, Math.ceil(floatIndex));
    const mix = floatIndex - leftIndex;
    const leftPoint = path[leftIndex];
    const rightPoint = path[rightIndex] ?? leftPoint;
    const value = leftPoint.ret_pct + (rightPoint.ret_pct - leftPoint.ret_pct) * mix;
    const leftMs = new Date(leftPoint.date).getTime();
    const rightMs = new Date(rightPoint.date).getTime();
    const date = Number.isFinite(leftMs) && Number.isFinite(rightMs)
      ? new Date(leftMs + (rightMs - leftMs) * mix)
      : new Date(leftPoint.date);
    const day = 1 + ratio * Math.max(totalDays - 1, 1);

    setHoverState({ x: clampedX, value, day, date });
  };

  return (
    <div>
      <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '12px' }}>
        21-day SPY path
      </div>
      <div style={{ position: 'relative', overflow: 'visible' }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: '100%', maxWidth: '100%', height: '238px', display: 'block', overflow: 'visible' }}
          onMouseMove={onMouseMove}
          onMouseLeave={() => setHoverState(null)}
        >
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={padL}
                y1={yForValue(tick)}
                x2={W - padR}
                y2={yForValue(tick)}
                stroke="rgba(255,255,255,0.04)"
                strokeWidth="0.5"
              />
              <text
                x={padL - 6}
                y={yForValue(tick) + 3}
                textAnchor="end"
                fill={T.textMuted}
                style={{ fontFamily: T.mono, fontSize: '9px' }}
              >
                {formatAccountingPct(tick)}
              </text>
            </g>
          ))}

          <polyline
            points={points}
            fill="none"
            stroke={lineColor}
            strokeWidth="1.25"
            strokeLinejoin="miter"
            strokeLinecap="square"
          />

          {hoverState && hoveredX !== null && hoveredY !== null && (
            <g pointerEvents="none">
              <line
                x1={hoveredX}
                y1={padT}
                x2={hoveredX}
                y2={H - padB}
                stroke="rgba(255,255,255,0.24)"
                strokeWidth="0.75"
                strokeDasharray="3 4"
              />
              <line
                x1={padL}
                y1={hoveredY}
                x2={W - padR}
                y2={hoveredY}
                stroke="rgba(255,255,255,0.18)"
                strokeWidth="0.75"
                strokeDasharray="3 4"
              />
              <circle cx={hoveredX} cy={hoveredY} r="3.2" fill={T.bg} stroke={lineColor} strokeWidth="1.5" />
            </g>
          )}

          <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" />

          {xTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={xForDay(tick)}
                y1={H - padB}
                x2={xForDay(tick)}
                y2={H - padB + 4}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth="0.5"
              />
              <text
                x={xForDay(tick)}
                y={H - 8}
                textAnchor="middle"
                fill={T.textMuted}
                style={{ fontFamily: T.mono, fontSize: '9px' }}
              >
                {formatDayNumber(tick)}
              </text>
            </g>
          ))}
        </svg>

        {hoverState && hoveredX !== null && hoveredY !== null && (
          <>
            <div
              style={{
                position: 'absolute',
                left: `${(hoveredX / W) * 100}%`,
                top: `${((H - padB) / H) * 100}%`,
                transform: 'translate(-50%, 10px)',
                padding: '5px 8px',
                background: 'rgba(7,7,10,0.94)',
                border: `0.5px solid ${T.border}`,
                color: 'rgba(255,255,255,0.82)',
                fontFamily: T.mono,
                fontSize: '10px',
                whiteSpace: 'nowrap',
                pointerEvents: 'none',
                boxShadow: '0 8px 24px rgba(0,0,0,0.28)',
              }}
            >
              {`D${hoveredDay ?? 1} · ${hoverDateLabel}`}
            </div>
            <div
              style={{
                position: 'absolute',
                right: '2px',
                top: `${(hoveredY / H) * 100}%`,
                transform: 'translateY(-50%)',
                padding: '5px 8px',
                background: 'rgba(7,7,10,0.94)',
                border: `0.5px solid ${T.border}`,
                color: hoveredColor,
                fontFamily: T.mono,
                fontSize: '10px',
                whiteSpace: 'nowrap',
                pointerEvents: 'none',
                boxShadow: '0 8px 24px rgba(0,0,0,0.28)',
              }}
            >
              {fmtRet(hoveredValue)}
            </div>
          </>
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap', marginTop: '12px', paddingTop: '10px', borderTop: `0.5px solid ${T.borderSub}` }}>
        <div>
          <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '3px' }}>
            21D return
          </div>
          <div style={{ fontFamily: T.mono, fontSize: '14px', fontWeight: 300, color: lineColor }}>
            {fmtRet(analogue.forward_returns?.['21d'])}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '3px' }}>
            Max DD
          </div>
          <div style={{ fontFamily: T.mono, fontSize: '14px', fontWeight: 300, color: T.dn }}>
            {fmtRet(analogue.risk_profile?.max_drawdown_5d)}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '3px' }}>
            Max up
          </div>
          <div style={{ fontFamily: T.mono, fontSize: '14px', fontWeight: 300, color: T.up }}>
            {fmtRet(analogue.risk_profile?.max_upside_5d)}
          </div>
        </div>
      </div>
    </div>
  );
}

function NarrativePanel({ date }: { date: string }) {
  const authFetcher = useAuthFetcher();
  const { data, isLoading, error } = useSWR<NarrativeData>(
    `/api/narrative/historical/${date}`,
    authFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 300000,
    }
  );

  return (
    <div>
      <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '12px' }}>
        Narrative
      </div>

      {isLoading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <SkeletonBlock width="24%" height={10} />
          <SkeletonText lines={3} widths={['100%', '94%', '72%']} lineHeight={11} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))', gap: '12px' }}>
            <SkeletonBlock height={86} />
            <SkeletonBlock height={86} />
          </div>
        </div>
      )}

      {error && (
        <div style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.dn }}>
          Unable to load historical narrative.
        </div>
      )}

      {data && !isLoading && !error && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {data.narrative.regime_verdict && (
            <div style={{ background: 'rgba(255,255,255,0.02)', border: `0.5px solid ${T.border}`, padding: '10px 12px' }}>
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '4px' }}>
                Regime verdict
              </div>
              <div style={{ fontFamily: T.sans, fontSize: '13px', color: T.text }}>
                {data.narrative.regime_verdict}
              </div>
            </div>
          )}

          {data.narrative.summary && (
            <div>
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                Summary
              </div>
              <div style={{ fontFamily: T.sans, fontSize: '13.5px', lineHeight: 1.7, color: 'rgba(255,255,255,0.72)' }}>
                {data.narrative.summary}
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))', gap: '14px' }}>
            <div>
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                Key signals
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {(data.narrative.key_signals ?? []).length > 0 ? data.narrative.key_signals.map((signal, idx) => (
                  <div key={idx} style={{ background: `${T.up}10`, border: `0.5px solid ${T.up}30`, padding: '8px 10px', fontFamily: T.sans, fontSize: '12.5px', lineHeight: 1.55, color: T.up }}>
                    {signal}
                  </div>
                )) : (
                  <div style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>No key signals returned.</div>
                )}
              </div>
            </div>

            <div>
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                Risks and uncertainties
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {(data.narrative.risks_and_uncertainties ?? []).length > 0 ? data.narrative.risks_and_uncertainties.map((risk, idx) => (
                  <div key={idx} style={{ background: `${T.dn}10`, border: `0.5px solid ${T.dn}30`, padding: '8px 10px', fontFamily: T.sans, fontSize: '12.5px', lineHeight: 1.55, color: T.dn }}>
                    {risk}
                  </div>
                )) : (
                  <div style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>No explicit risks returned.</div>
                )}
              </div>
            </div>
          </div>

          {data.narrative.outcome_note && (
            <div style={{ background: `${T.accent}10`, border: `0.5px solid ${T.accent}40`, padding: '10px 12px' }}>
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.accent, marginBottom: '4px' }}>
                Outcome note
              </div>
              <div style={{ fontFamily: T.sans, fontSize: '12.5px', color: 'rgba(255,255,255,0.72)', lineHeight: 1.6 }}>
                {data.narrative.outcome_note}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AnalogueRow({ a, isExpanded, onToggle }: {
  a: Analogue;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const fwd = a.forward_returns;
  const envColor = ENV_COLOR[a.environment] || T.mid;

  return (
    <div style={{ borderBottom: `0.5px solid ${T.borderSub}` }}>
      <div
        className="temper-interactive-row"
        onClick={onToggle}
        style={{
          display: 'grid',
          gridTemplateColumns: '90px 52px 130px 60px 72px 72px 72px',
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
      </div>

      {isExpanded && (
        <div style={{ background: 'rgba(255,255,255,0.012)', borderTop: `0.5px solid ${T.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(280px, 0.9fr)' }}>
            <div style={{ padding: '16px 20px', borderRight: `0.5px solid ${T.border}` }}>
              <HistoricalPathChart analogue={a} />
            </div>

            <div style={{ padding: '16px 20px' }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '12px' }}>
                Score components
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {Object.entries(a.score_components ?? {}).map(([k, v]) => {
                  const fill = v >= 6 ? T.up : v >= 4 ? T.wa : T.dn;
                  return (
                    <div key={k} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 28px', alignItems: 'center', gap: '10px', padding: '6px 0', borderBottom: `0.5px solid ${T.borderSub}` }}>
                      <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>
                        {k.replace(/_/g, ' ')}
                      </span>
                      <div style={{ height: '1px', background: 'rgba(255,255,255,0.05)' }}>
                        <div style={{ width: `${(v / 10) * 100}%`, height: '100%', background: fill }} />
                      </div>
                      <span style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: fill, textAlign: 'right' }}>
                        {v?.toFixed(1)}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '10px', marginTop: '16px', paddingTop: '12px', borderTop: `0.5px solid ${T.borderSub}` }}>
                {[
                  ['Score', a.score_total?.toFixed(1)],
                  ['Confidence', a.confidence?.toFixed(1)],
                  ['Score Δ', a.score_delta != null ? `${a.score_delta >= 0 ? '+' : ''}${a.score_delta.toFixed(1)}` : '—'],
                  ['VIX', a.vix_level?.toFixed(1) ?? '—'],
                  ['Breadth', a.sectors_green != null ? `${a.sectors_green}/11` : '—'],
                  ['SPY close', a.spy_close != null ? formatCurrency(a.spy_close) : '—'],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '4px' }}>
                      {label}
                    </div>
                    <div style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: 'rgba(255,255,255,0.78)' }}>
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div style={{ padding: '16px 20px', borderTop: `0.5px solid ${T.border}` }}>
            <NarrativePanel date={a.date} />
          </div>
        </div>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [topN, setTopN] = useState(15);
  const authFetcher = useAuthFetcher();

  const { data, isLoading, error } = useSWR(
    `/api/market/analogues?top_n=${topN}`,
    authFetcher,
    { refreshInterval: 300000 }
  );

  const toggle = (date: string) => setExpanded((prev) => (prev === date ? null : date));
  const agg = data?.aggregate_stats;
  const current = data?.current_state;

  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <section style={sx.panel}>
          <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
            <span style={sx.sectionLabel}>Market memory</span>
            <span style={sx.sectionMeta}>Historical analogues · when has the market been here before</span>
          </div>
        </section>

        {isLoading ? (
          <section style={sx.panel}>
            <div style={sx.panelBody}>
              <div style={{ padding: '0 0 18px' }}>
                <SkeletonBlock width="34%" height={12} style={{ marginBottom: '10px' }} />
                <SkeletonBlock width="52%" height={12} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', gap: '12px', marginBottom: '12px' }}>
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} style={{ ...sx.subPanel, padding: '14px 20px' }}>
                    <SkeletonBlock width="42%" height={10} style={{ marginBottom: '10px' }} />
                    <SkeletonBlock width="58%" height={20} style={{ marginBottom: '10px' }} />
                    <SkeletonBlock width="72%" height={10} />
                  </div>
                ))}
              </div>
              <SkeletonRows rows={8} columns={4} />
            </div>
          </section>
        ) : null}

        {error ? (
          <section style={sx.panel}>
            <div style={{ ...sx.panelBody, padding: '40px 24px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.dn }}>Error loading analogues.</span>
            </div>
          </section>
        ) : null}

        {data ? (
          <>
            <section style={sx.panel}>
              <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
                <span style={sx.sectionLabel}>Current conditions</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.8px', color: T.textMuted }}>Show top</span>
                  {[10, 15, 20].map((n) => (
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
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
              <div style={sx.panelBody}>
                <div style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: 'rgba(255,255,255,0.75)', letterSpacing: '0.3px', marginBottom: '4px' }}>
                  {data.conditions_matched}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: '11.5px', fontWeight: 300, color: T.textMuted }}>
                  {current?.asof_utc?.slice(0, 10)} · score {formatNumber(current?.score_total, 1)} · VIX {formatNumber(current?.vix_level, 1)} · {current?.sectors_green}/11 sectors green
                </div>
              </div>
            </section>

            {agg ? (
              <section style={sx.panel}>
                <div style={sx.panelHeader}>
                  <span style={sx.sectionLabel}>Aggregate outlook</span>
                  <span style={sx.sectionMeta}>{agg.n_analogues} comparable episodes</span>
                </div>
                <div style={{ ...sx.panelBody, display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', gap: '12px' }}>
                    {(['1d', '5d', '10d', '21d'] as const).map((h) => (
                      <div key={h} style={sx.subPanel}>
                        <FwdCard horizon={h} stats={agg.forward_returns[h]} />
                      </div>
                    ))}
                  </div>

                  {agg.risk_profile ? (
                    <div style={sx.subPanel}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
                        {[
                          { label: '21D risk profile', val: null },
                          { label: 'Median max DD', val: agg.risk_profile.median_max_drawdown_21d, color: T.dn, fmt: fmtRet },
                          { label: 'Median max upside', val: agg.risk_profile.median_max_upside_21d, color: T.up, fmt: fmtRet },
                          { label: 'EV (21d)', val: agg.risk_profile.expected_value_21d, color: (agg.risk_profile.expected_value_21d ?? 0) >= 0 ? T.up : T.dn, fmt: fmtRet },
                          { label: 'Win rate', val: agg.risk_profile.win_rate_21d, color: T.mid, fmt: (v: number) => `${formatNumber(v, 1)}%` },
                          { label: 'Wtd R/R', val: agg.risk_profile.weighted_reward_risk_21d, color: T.mid, fmt: (v: number) => `${formatNumber(v, 2)}×` },
                          { label: 'Worst 21D', val: agg.risk_profile.worst_drawdown_21d, color: T.dn, fmt: fmtRet },
                        ].map(({ label, val, color, fmt }, i) => (
                          <div key={label} style={{ padding: '12px 20px', borderRight: i < 4 ? `0.5px solid ${T.border}` : 'none' }}>
                            <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '5px' }}>
                              {label}
                            </div>
                            {val !== null && val !== undefined && fmt ? (
                              <div style={{ fontFamily: T.mono, fontSize: '17px', fontWeight: 300, color: color ?? T.text }}>
                                {fmt(val)}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}

            <section style={sx.panel}>
              <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
                <span style={sx.sectionLabel}>Comparable episodes</span>
                <span style={sx.sectionMeta}>Click any row to expand</span>
              </div>
              <div style={sx.panelBody}>
                <div style={{ overflowX: 'auto' }}>
                  <div style={{ minWidth: '610px' }}>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '90px 52px 130px 60px 72px 72px 72px',
                        padding: '10px 18px',
                        borderBottom: `0.5px solid ${T.border}`,
                        background: T.sectionBg,
                      }}
                    >
                      {['Date', 'Score', 'Environment', 'VIX', '1D fwd', '5D fwd', '21D fwd'].map((h) => (
                        <span key={h} style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted }}>
                          {h}
                        </span>
                      ))}
                    </div>

                    {data.analogues?.map((a: Analogue) => (
                      <AnalogueRow key={a.date} a={a} isExpanded={expanded === a.date} onToggle={() => toggle(a.date)} />
                    ))}
                  </div>
                </div>

                <div style={{ padding: '16px 6px 0' }}>
                  <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted, lineHeight: 1.5 }}>
                    Analogues ranked by similarity to current conditions (environment + score range + VIX regime + breadth + score momentum).
                  </span>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}